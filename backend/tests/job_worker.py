"""Scripted stage handlers, and a worker process that tests can kill.

python -m backend.tests.job_worker <store> <run id> <log> [<question id>:<stage>]

Every handler call is written to the log before it does anything, so the log
shows exactly which stages ran, in which process, even when that process is
killed. With the last argument, the worker hangs inside that stage of that
question until it is killed.
"""

import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from pydantic import JsonValue

from agent.llm import Spend
from backend.contracts.investigation import Question, QuestionStage, QuestionStatus
from backend.jobs import Engine, Handler, Step
from backend.run_store import RunStore

Stage = QuestionStage
PATH: list[Stage] = [
    Stage.FRAME,
    Stage.GATHER,
    Stage.HYPOTHESIZE,
    Stage.CHALLENGE,
    Stage.DECIDE,
    Stage.RECORD,
]


def trail(state: Mapping[str, JsonValue]) -> list[JsonValue]:
    stages = state.get("trail")
    return list(stages) if isinstance(stages, list) else []


def logged_handlers(log: Path, hang: tuple[str, str] | None = None) -> dict[Stage, Handler]:
    """Handlers that walk the straight path and carry the list of stages run as their state."""

    def handler_for(stage: Stage) -> Handler:
        def handle(question: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
            with log.open("a", encoding="utf-8") as out:
                out.write(f"{os.getpid()} {question.id} {stage.value}\n")
                out.flush()
                os.fsync(out.fileno())
            if hang == (question.id, stage.value):
                while True:
                    time.sleep(60)
            spend.prompt_tokens += 100
            seen = [*trail(state), stage.value]
            activity = (f"Ran {stage.value} for {question.id}",)
            if stage is Stage.RECORD:
                return Step(
                    status=QuestionStatus.ANSWERED, answer={"trail": seen}, activity=activity
                )
            return Step(next=PATH[PATH.index(stage) + 1], state={"trail": seen}, activity=activity)

        return handle

    return {stage: handler_for(stage) for stage in PATH}


def main(argv: list[str]) -> int:
    store, run_id, log = RunStore(Path(argv[0])), argv[1], Path(argv[2])
    hang = tuple(argv[3].split(":", 1)) if len(argv) > 3 else None
    run = Engine(store, logged_handlers(log, hang)).run(run_id)  # ty: ignore[invalid-argument-type]
    print(run.lifecycle.value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
