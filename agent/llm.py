"""Model adapter: stateless, schema-constrained requests under a question's budget (M3.1).

One question is one narrow judgment (PROJECT_PLAN §3.1). It may take several
requests, and each of them stands alone: the adapter sends a system prompt and
a user prompt, never a conversation, and turns the server's prompt cache off
(§9). llama.cpp's grammar sampler constrains the answer to a JSON Schema, so
what can go wrong is the judgment or the machine, not the format.

A question spends against its ``Budget`` (§6):

- Prompt tokens are counted with ``/tokenize`` before anything is sent, so
  evidence that does not fit costs no prefill. That count leaves out the chat
  template's own tokens; what is charged is the server's count of the request
  it answered.
- Seconds cover every attempt, the token count, and the pauses between retries.
- Retries are for transient failures only: timeouts, dropped connections, 5xx.
  A request the server refuses, or an answer that is cut off or malformed, is
  deterministic at a fixed seed, so sending it again would only spend time.

Running out of tokens or time is a ``BudgetStop``. Running out of retries
raises the failure that kept happening, because that is a fault of the model
server and not of the question's budget.

No model is loaded before the preflight passes (HARDWARE.md, "Memory budget").
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Protocol, Self

import httpx

from backend.contracts.investigation import Budget
from backend.llama_server import LlamaServer
from backend.preflight import PreflightResult
from backend.redaction import Redactor

CHAT = "/v1/chat/completions"
TOKENIZE = "/tokenize"


class ModelServer(Protocol):
    """What the adapter needs from ``LlamaServer``; tests script a fake in its place."""

    client: httpx.Client

    def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class ModelRequest:
    """One self-contained question. There is no field for earlier turns, by design."""

    name: str
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int = 512
    thinking: bool = False
    temperature: float = 0.0
    seed: int = 42

    def body(self, redactor: Redactor | None = None) -> dict[str, Any]:
        redactor = redactor or Redactor.configured()
        try:
            schema = redactor.strings(self.schema)
        except ValueError:
            raise RequestRejected("A credential occurs in a request schema or identity.") from None
        if schema != self.schema or redactor.text(self.name) != self.name:
            raise RequestRejected("A credential occurs in a request schema or identity.")
        return {
            "messages": [
                {"role": "system", "content": redactor.text(self.system)},
                {"role": "user", "content": redactor.text(self.user)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": self.name, "schema": self.schema, "strict": True},
            },
            "chat_template_kwargs": {"enable_thinking": self.thinking},
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "seed": self.seed,
            "cache_prompt": False,
        }


@dataclass(frozen=True)
class JsonAnswer:
    data: dict[str, Any]
    raw: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float  # of the attempt that answered
    attempts: int = 1


@dataclass
class Spend:
    """What one question has used of its budget, across all of its requests."""

    budget: Budget
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    retries: int = 0

    @property
    def prompt_tokens_left(self) -> int:
        return self.budget.max_prompt_tokens - self.prompt_tokens

    @property
    def seconds_left(self) -> float:
        return self.budget.max_seconds - self.seconds

    @property
    def retries_left(self) -> int:
        return self.budget.max_retries - self.retries


class ModelError(RuntimeError):
    """A model request ended without a usable answer."""


class PreflightRefused(ModelError):
    """Not enough free memory to load the model without paging; nothing was started."""

    def __init__(self, result: PreflightResult) -> None:
        super().__init__(result.message)
        self.result = result


class BudgetStop(ModelError):
    """The question used up its budget. The model server was not at fault."""

    def __init__(self, reason: Literal["prompt_tokens", "seconds"], message: str) -> None:
        super().__init__(message)
        self.reason = reason


class ModelTimeout(ModelError):
    """No answer within an attempt's time limit, and no retry is left."""


class ModelUnavailable(ModelError):
    """The server dropped the connection or answered 5xx, and no retry is left."""


class RequestRejected(ModelError):
    """The server refused the request (4xx). Sending it again cannot help."""


class AnswerError(ModelError):
    """The server returned no parseable JSON object."""


class AnswerTruncated(AnswerError):
    """The answer reached ``max_tokens`` before its JSON was complete."""


def _usage(result: dict[str, Any]) -> tuple[int, int]:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    return (
        prompt if isinstance(prompt, int) else 0,
        completion if isinstance(completion, int) else 0,
    )


def _parse(result: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        choice = result["choices"][0]
        raw = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise AnswerError("no JSON answer: missing completion content") from error
    if isinstance(choice, dict) and choice.get("finish_reason") == "length":
        raise AnswerTruncated("answer cut off at the token limit")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise AnswerError("no JSON answer: invalid completion content") from error
    if not isinstance(data, dict):
        raise AnswerError("answer is not a JSON object")
    return data, raw


class ModelAdapter:
    """The only way the investigator reaches the model.

    ``attempt_seconds`` caps a single attempt so that a stalled request can be
    retried inside the question's time budget; without it an attempt may use
    all the time the question has left.
    """

    def __init__(
        self,
        server: ModelServer,
        *,
        preflight: Callable[[], PreflightResult],
        attempt_seconds: float | None = None,
        retry_pauses: tuple[float, ...] = (0.5, 2.0),
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
        redactor: Redactor | None = None,
    ) -> None:
        if attempt_seconds is not None and attempt_seconds <= 0:
            raise ValueError("attempt_seconds must be positive")
        if not retry_pauses or any(pause < 0 for pause in retry_pauses):
            raise ValueError("retry_pauses needs at least one non-negative pause")
        self._server = server
        self._preflight = preflight
        self._attempt_seconds = attempt_seconds
        self._retry_pauses = retry_pauses
        self._clock = clock
        self._sleep = sleep
        self._started = False
        self.redactor = redactor or getattr(server, "redactor", None) or Redactor.configured()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def start(self) -> None:
        """Check memory, then load the model. A refusal leaves the server untouched."""
        if self._started:
            return
        result = self._preflight()
        if not result.ok:
            raise PreflightRefused(result)
        self._server.start()
        self._started = True

    def close(self) -> None:
        if self._started:
            self._started = False
            self._server.stop()

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        """Ask once and charge ``spend``; raises instead of returning a partial answer."""
        body = request.body(self.redactor)
        self.start()
        text = "\n".join(message["content"] for message in body["messages"])
        counted, _, _ = self._send(TOKENIZE, {"content": text, "add_special": False}, spend)
        tokens = counted.get("tokens")
        if not isinstance(tokens, list):
            raise AnswerError("/tokenize returned no token list")
        if len(tokens) > spend.prompt_tokens_left:
            raise BudgetStop(
                "prompt_tokens",
                f"This evidence needs at least {len(tokens)} prompt tokens, and the question "
                f"has {max(spend.prompt_tokens_left, 0)} of its "
                f"{spend.budget.max_prompt_tokens} left.",
            )
        result, seconds, attempts = self._send(CHAT, body, spend)
        prompt, completion = _usage(result)
        prompt = prompt or len(tokens)
        spend.requests += 1
        spend.prompt_tokens += prompt
        spend.completion_tokens += completion
        data, raw = _parse(result)
        return JsonAnswer(data, raw, prompt, completion, seconds, attempts)

    def _send(
        self, path: str, body: dict[str, Any], spend: Spend
    ) -> tuple[dict[str, Any], float, int]:
        """POST until answered, retrying transient failures inside the budget."""
        out_of_time = (
            f"The question used its {spend.budget.max_seconds:g} s time budget "
            "before the model answered."
        )
        attempts = 0
        while True:
            left = spend.seconds_left
            if left <= 0:
                raise BudgetStop("seconds", out_of_time)
            limit = left if self._attempt_seconds is None else min(left, self._attempt_seconds)
            attempts += 1
            started = self._clock()
            outcome = self._attempt(path, body, limit)
            seconds = self._clock() - started
            spend.seconds += seconds
            if isinstance(outcome, httpx.Response):
                if outcome.status_code != 200:
                    raise RequestRejected(
                        f"The model server refused the request ({outcome.status_code})."
                    )
                try:
                    result = outcome.json()
                except ValueError as error:
                    raise AnswerError("no JSON answer: invalid server response") from error
                if not isinstance(result, dict):
                    raise AnswerError("no JSON answer: invalid server response")
                return result, seconds, attempts
            # An attempt that was given all the remaining time and still timed out
            # has spent the budget, whatever the two clocks say to the millisecond.
            if isinstance(outcome, ModelTimeout) and limit == left:
                spend.seconds = max(spend.seconds, spend.budget.max_seconds)
                raise BudgetStop("seconds", out_of_time) from outcome
            if spend.retries_left <= 0:
                raise outcome
            pause = self._retry_pauses[min(attempts, len(self._retry_pauses)) - 1]
            if pause >= spend.seconds_left:
                # Waiting would use up the rest of the time, so stop without waiting.
                raise BudgetStop("seconds", out_of_time) from outcome
            spend.retries += 1
            self._sleep(pause)
            spend.seconds += pause

    def _attempt(
        self, path: str, body: dict[str, Any], limit: float
    ) -> httpx.Response | ModelTimeout | ModelUnavailable:
        try:
            response = self._server.client.post(path, json=body, timeout=limit)
        except httpx.TimeoutException:
            return ModelTimeout(f"No answer from the model within {limit:.1f} s.")
        except httpx.TransportError as error:
            return ModelUnavailable(f"The model server did not answer ({type(error).__name__}).")
        if response.status_code >= 500:
            return ModelUnavailable(f"The model server answered {response.status_code}.")
        return response


def ask_json(
    server: LlamaServer,
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    name: str,
    max_tokens: int = 512,
    thinking: bool = False,
) -> JsonAnswer:
    """One unbudgeted attempt on a running server, for the recorded baselines and M0.6.

    Same request and same parsing as ``ModelAdapter.ask``; investigations use the adapter.
    """
    request = ModelRequest(
        name=name, system=system, user=user, schema=schema, max_tokens=max_tokens, thinking=thinking
    )
    started = time.perf_counter()
    result = server.post(CHAT, request.body(server.redactor))
    seconds = time.perf_counter() - started
    data, raw = _parse(result)
    prompt, completion = _usage(result)
    return JsonAnswer(data, raw, prompt, completion, seconds)
