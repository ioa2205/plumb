"""A scripted stand-in for ``llama-server`` on loopback.

It answers ``/tokenize`` with one token per whitespace-separated word and
plays back a queue of replies for chat requests, recording everything it is
sent. A reply can answer, fail with a status, drop the connection, or hang
until the test ends, which is how a real timeout is exercised.
"""

import json
import threading
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal

import httpx

LOOPBACK = "127.0.0.1"


@dataclass(frozen=True)
class Reply:
    kind: Literal["answer", "hang", "drop"] = "answer"
    status: int = 200
    body: Any = None


def answer(
    content: object,
    *,
    prompt_tokens: int | None = 20,
    completion_tokens: int = 5,
    finish_reason: str = "stop",
) -> Reply:
    """A chat completion whose message is ``content`` (encoded as JSON unless a string)."""
    text = content if isinstance(content, str) else json.dumps(content)
    body: dict[str, Any] = {
        "choices": [{"message": {"content": text}, "finish_reason": finish_reason}]
    }
    if prompt_tokens is not None:
        body["usage"] = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    return Reply(body=body)


def error(status: int, message: str = "unavailable") -> Reply:
    return Reply(status=status, body={"error": {"message": message}})


HANG = Reply(kind="hang")
DROP = Reply(kind="drop")


class FakeLlama:
    def __init__(self, *replies: Reply) -> None:
        self.replies: deque[Reply] = deque(replies)
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.starts = 0
        self.stops = 0
        self._release = threading.Event()
        self._http = ThreadingHTTPServer((LOOPBACK, 0), self._handler())
        self._http.daemon_threads = True
        # A short poll keeps shutdown, and so every test's teardown, quick.
        self._thread = threading.Thread(
            target=self._http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.client = httpx.Client(base_url=f"http://{LOOPBACK}:{self._http.server_port}")

    @property
    def chats(self) -> list[dict[str, Any]]:
        return [body for path, body in self.requests if path == "/v1/chat/completions"]

    def start(self) -> None:
        self.starts += 1
        self._thread.start()

    def stop(self) -> None:
        self.stops += 1
        self.shutdown()

    def shutdown(self) -> None:
        """Release hanging replies and free the port; safe to call more than once."""
        self._release.set()
        if self._thread.is_alive():
            self._http.shutdown()
            self._thread.join(timeout=5)
        self._http.server_close()
        self.client.close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                fake.requests.append((self.path, body))
                if self.path == "/tokenize":
                    self._json(200, {"tokens": list(range(len(body["content"].split())))})
                    return
                reply = fake.replies.popleft() if fake.replies else error(500, "script is empty")
                if reply.kind == "hang":
                    fake._release.wait()
                    self.close_connection = True
                elif reply.kind == "drop":
                    self.close_connection = True
                else:
                    self._json(reply.status, reply.body)

            def _json(self, status: int, body: object) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler
