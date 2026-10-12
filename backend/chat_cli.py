"""The interactive terminal chat: type in your own words, no IDs or command syntax.

A message never starts work. When a message asks for work, the proposal is shown
and the terminal asks a yes/no question; only that explicit answer runs the
existing bounded command.
"""

import time
from collections.abc import Callable
from contextlib import suppress

from backend.chat import Chats, saved_results
from backend.contracts.chat import ChatAsk, ChatCreate, ChatTurn, ChatView, Intent
from backend.jobs import WorkerBusy
from backend.redaction import Redactor
from backend.settings import Settings

WELCOME = (
    "Plumb. Type a message in your own words: a question, a folder to review, or a website\n"
    "you are authorized to test. /select picks a saved result, /new starts over, /quit leaves.\n"
    "Ctrl+C stops a running answer."
)
Read = Callable[[str], str]
Write = Callable[[str], None]


def show_turn(turn: ChatTurn, write: Write) -> None:
    how = {
        "code": "decided by code",
        "model": "decided by the local model",
        "model_reordered": "decided by the local model on a second, independent try",
        "user": "your choice",
        "stop": "not decided",
    }[turn.intent_rung]
    write(f"\n{turn.interpretation} ({how})")
    for part in turn.parts:
        write("\n" + part.text)
        for item in part.evidence:
            write(f"  [{item.reference_id}] {item.label}: {item.quote.strip()}")
        write(f"  — {part.basis}")
    if turn.task is not None and turn.task.steps:
        write("\nWhat would happen, only after you confirm:")
        for number, step in enumerate(turn.task.steps, start=1):
            write(f"  {number}. {step}")
    if turn.model_requests:
        write(f"  (local model: {turn.model_requests} requests, {turn.model_seconds:.0f} s)")


def ask_and_wait(worker: Chats, view: ChatView, request: ChatAsk, write: Write) -> ChatView:
    worker.start(view.chat_id, request)
    shown = None
    try:
        while True:
            current = worker.read(view.chat_id)
            if current.state != "running":
                return current
            if current.progress and current.progress != shown:
                shown = current.progress
                write("  … " + shown)
            time.sleep(0.2)
    except KeyboardInterrupt:
        worker.cancel(view.chat_id)
        write("  Stopping. Earlier turns are kept.")
        return worker.wait(view.chat_id, 70)


def choose(read: Read, write: Write, labels: list[str], question: str) -> int | None:
    for number, label in enumerate(labels, start=1):
        write(f"  {number}. {label}")
    answer = read(question + " (number, or Enter to skip) > ").strip()
    return int(answer) - 1 if answer.isdigit() and 1 <= int(answer) <= len(labels) else None


def yes(read: Read, question: str) -> bool:
    return read(question + " [y/N] > ").strip().lower() in {"y", "yes"}


def select_result(worker: Chats, view: ChatView, read: Read, write: Write) -> ChatView:
    from backend.web_store import JourneyStore

    results = saved_results(worker.settings)
    with suppress(OSError, ValueError):
        results += [
            ("website", journey.journey_id, f"Website test of {journey.scope.name}")
            for journey in JourneyStore(worker.settings).list(5)
        ]
    if not results:
        write("No saved review or website test was found yet.")
        return view
    picked = choose(read, write, [label for _, _, label in results], "Which result?")
    if picked is None:
        return view
    kind, identifier, label = results[picked]
    try:
        worker.release_model()  # reading the result takes the same lock as the model
        view = worker.select(
            view.chat_id,
            ChatCreate(target_kind=kind, target_id=identifier),  # ty: ignore[invalid-argument-type]
        )
        write(f"Selected: {label}. Follow-up questions use it.")
    except (ValueError, OSError, WorkerBusy):
        write("That result cannot be read safely now. Nothing was selected.")
    return view


def inspect_now(worker: Chats, view: ChatView, folder: str, write: Write) -> ChatView:
    """The existing read-only inspection, run only after an explicit yes."""
    from backend.setup_reads import inspect_folder

    worker.release_model()
    try:
        result = inspect_folder(worker.settings, folder)
    except WorkerBusy:
        write("Another Plumb task is running. Try again when it has finished.")
        return view
    except (OSError, ValueError, RuntimeError):
        write(
            "This folder could not be inspected safely. Check the path and run plumb setup. "
            "No code from it was run."
        )
        return view
    redactor = Redactor.configured(worker.settings)
    write(
        redactor.text(
            f"Inspected {result.name}: {result.included_files} files read, "
            f"{result.entries_total} entry points recognized, {result.excluded_files} files "
            "left out. No code was run and no model was used."
        )
    )
    for limitation in result.limitations[:3]:
        write("  Limit: " + redactor.text(limitation))
    if result.inspection_id is None:
        return view
    view = worker.select(
        view.chat_id, ChatCreate(target_kind="inspection", target_id=result.inspection_id)
    )
    write(
        "This folder is now selected: ask about it in your own words. To look for problems, "
        f'run: plumb review "{folder}"'
    )
    return view


def run_repl(
    settings: Settings,
    *,
    read: Read | None = None,
    write: Write = print,
    first_message: str | None = None,
    once: bool = False,
    profile: str = "auto",
    max_seconds: int = 300,
) -> int:
    read = read or input
    worker = Chats(settings, hold_model=not once)
    try:
        view = worker.new()
        if not once:
            write(WELCOME)
            write(view.limits)
        pending: tuple[str, Intent | None] | None = (first_message, None) if first_message else None
        while True:
            if pending is None:
                if once:
                    return 0
                try:
                    line = read("\nyou > ").strip()
                except (EOFError, KeyboardInterrupt, OSError):
                    # No more input (closed terminal or a pipe that ended): leave quietly.
                    write("")
                    return 0
                if not line:
                    continue
                if line in {"/quit", "/exit"}:
                    return 0
                if line == "/new":
                    view = worker.new()
                    write("New chat. Nothing is selected.")
                    continue
                if line == "/select":
                    view = select_result(worker, view, read, write)
                    continue
                pending = (line, None)
            message, choice = pending
            pending = None
            try:
                view = ask_and_wait(
                    worker,
                    view,
                    ChatAsk(
                        prompt=message, choice=choice, profile=profile, max_seconds=max_seconds
                    ),
                    write,
                )
            except ValueError as error:
                write(f"Not sent: {error}.")
                continue
            if view.state != "completed" or not view.turns:
                write(view.message)
                if once:
                    return 1
                continue
            turn = view.turns[-1]
            show_turn(turn, write)
            if once:
                return 0
            if turn.choices:
                picked = choose(
                    read, write, [item.label for item in turn.choices], "What did you mean?"
                )
                if picked is not None:
                    pending = (message, turn.choices[picked].intent)
            elif turn.task is not None:
                task = turn.task
                if task.kind == "choose_result":
                    view = select_result(worker, view, read, write)
                elif (
                    task.kind == "inspect_folder"
                    and task.ready
                    and task.folder
                    and yes(read, f"Inspect {task.folder} now? Nothing in it is run.")
                ):
                    view = inspect_now(worker, view, task.folder, write)
                elif task.kind == "website_setup" and yes(
                    read, "Start the website setup now? Nothing is visited during setup."
                ):
                    from backend.web_cli import setup_from_chat

                    worker.release_model()
                    view = setup_from_chat(worker, view, task.url, read, write)
    finally:
        worker.close()
