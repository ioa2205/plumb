"""Pictures of the Ask and Website pages at 1440 and 390 px, Day and Night.

    pnpm --dir frontend build
    uv run --extra browser python frontend/scripts/ask_website_images.py [output-folder]

Serves the built workbench from a throwaway data folder holding only the
synthetic fixtures in ``frontend/scripts/fixtures`` (a chat and one real practice
journey), signs in through the ordinary one-time link, and photographs the pages
with the provisioned browser at true viewport widths. No model, no fixture
process and nothing external is started. Pictures go to ``tmp/``, which is never
committed.
"""

import base64
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

from backend.chat import Chats
from backend.contracts.chat import ChatView
from backend.contracts.web_journey import HumanAuthView, JourneyView
from backend.serve import bind, server
from backend.settings import Settings
from backend.setup.browser import verified_executable
from backend.web_api import WebsiteJobs
from backend.web_human import HumanChannel
from backend.web_report import write_report
from backend.web_store import JourneyStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "frontend" / "scripts" / "fixtures"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tmp" / "ask-website-ui-shots"
    output.mkdir(parents=True, exist_ok=True)
    browser_settings = Settings()
    settings = Settings(data_dir=Path(tempfile.mkdtemp(prefix="plumb-ui-")), port=free_port())
    chat = ChatView.model_validate(json.loads((FIXTURES / "chat-views.json").read_bytes())["view"])
    Chats(settings).save(chat)
    views = json.loads((FIXTURES / "website-views.json").read_bytes())
    store = JourneyStore(settings)
    done = JourneyView.model_validate(views["done"])
    planned = JourneyView.model_validate({**views["planned"], "journey_id": "journey-" + "b" * 32})
    waiting = JourneyView.model_validate(
        {**views["waiting"], "journey_id": "journey-" + "c" * 32, "report_path": None}
    )
    store.save(planned)
    store.save(waiting)
    store.save(done.model_copy(update={"report_path": None}))
    store.save(done.model_copy(update={"report_path": str(write_report(settings, done))}))

    # A synthetic private challenge for visual QA only. No live account/session,
    # challenge input or screenshot from a real website is persisted.
    human_view = planned.model_copy(
        update={
            "journey_id": "journey-" + "d" * 32,
            "status": "handoff",
            "stage": "authenticate",
            "activity": "Complete the private synthetic challenge.",
        }
    )
    store.save(human_view)
    jobs = WebsiteJobs(settings)
    channel = HumanChannel()
    jobs.humans[human_view.journey_id] = channel
    # Keep this synthetic view live for QA; production exposes dead workers as
    # paused. The placeholder runs no journey and accepts no challenge actions.
    human_closed = threading.Event()
    human_worker = threading.Thread(target=human_closed.wait, daemon=True)
    human_worker.start()
    jobs.threads[human_view.journey_id] = human_worker
    import backend.web_api as web_api

    original_jobs = web_api.WebsiteJobs
    web_api.WebsiteJobs = lambda _: jobs  # ty: ignore[invalid-assignment]

    listener = bind(settings.port)
    try:
        running, app = server(listener, settings)
    finally:
        web_api.WebsiteJobs = original_jobs
    thread = threading.Thread(target=running.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    while not running.started:
        time.sleep(0.05)
    origin = f"http://127.0.0.1:{settings.port}"
    pages = {
        "ask-empty": "/ask/",
        "ask-chat": f"/ask/?chat={chat.chat_id}",
        "website-start": "/website/",
        "website-setup": "/website/",
        "website-plan": f"/website/?journey={planned.journey_id}",
        "website-waiting": f"/website/?journey={waiting.journey_id}",
        "website-human": f"/website/?journey={human_view.journey_id}",
        "website-done": f"/website/?journey={done.journey_id}",
    }
    problems: list[str] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(verified_executable(browser_settings)),
                headless=True,
                chromium_sandbox=True,
            )
            first = browser.new_context()
            entry = first.new_page()
            entry.set_viewport_size({"width": 1280, "height": 900})
            entry.set_content(
                "<h1>Synthetic sign-in challenge</h1><p>Enter the one-time test code.</p>"
                "<label>One-time code <input autocomplete='one-time-code'></label>"
                "<p><button>Continue</button></p>"
            )
            step = next(step for step in human_view.plan.steps if step.action == "sign_in")
            account = next(
                account
                for account in human_view.scope.accounts
                if account.account_id == step.account_id
            )
            channel.publish(
                HumanAuthView(
                    view_id="e" * 32,
                    step_id=step.step_id,
                    account_id=account.account_id,
                    label=account.label,
                    challenge="one_time_code",
                    question="Complete this synthetic challenge. Input values are hidden.",
                    screenshot_png=base64.b64encode(entry.screenshot()).decode("ascii"),
                )
            )
            entry.goto(app.state.gate.bootstrap_url)
            cookies = first.cookies()
            first.close()
            for theme, scheme in (("day", "light"), ("night", "dark")):
                for width in (1440, 390):
                    context = browser.new_context(
                        viewport={"width": width, "height": 900}, color_scheme=scheme
                    )
                    context.add_cookies(cookies)  # ty: ignore[invalid-argument-type]
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda error, sink=errors: sink.append(str(error)))
                    page.on(
                        "console",
                        lambda message, sink=errors: (
                            sink.append(message.text) if message.type == "error" else None
                        ),
                    )
                    for name, path in pages.items():
                        page.goto(origin + path, wait_until="networkidle")
                        if name == "website-setup":
                            page.get_by_label("Website address", exact=True).fill(
                                "https://owned.example"
                            )
                            page.get_by_label("Purpose of this test", exact=True).fill(
                                "Review our designated practice accounts"
                            )
                            page.get_by_label(
                                "Who authorized this test? Include their role", exact=True
                            ).fill("Website owner")
                            page.get_by_label(
                                "Authorization reference, such as a ticket and date", exact=True
                            ).fill("Owned test ticket 17")
                            page.get_by_label(
                                "I confirm these exact addresses, accounts, objects and actions "
                                "are authorized within these limits.",
                                exact=True,
                            ).check()
                        if name == "website-done":
                            for summary in page.locator("details > summary").all():
                                summary.click()
                            page.get_by_role("button", name="Read the report").click()
                            page.wait_for_selector("pre")
                        if name == "website-human":
                            page.get_by_role(
                                "button", name="Submit challenge", exact=True
                            ).wait_for()
                        page.wait_for_timeout(300)
                        overflow = page.evaluate(
                            "document.documentElement.scrollWidth > window.innerWidth + 1"
                        )
                        if overflow:
                            problems.append(f"{name} {width} {theme}: horizontal overflow")
                        page.screenshot(
                            path=str(output / f"{name}-{width}-{theme}.png"), full_page=True
                        )
                        if name == "website-setup":
                            with page.expect_response(
                                lambda response: (
                                    response.url == origin + "/api/websites"
                                    and response.request.method == "POST"
                                )
                            ) as created:
                                page.get_by_role(
                                    "button", name="Create the plan", exact=True
                                ).click()
                            response = created.value
                            view = response.json()
                            if (
                                response.status != 200
                                or view.get("status") != "planned"
                                or view.get("scope", {}).get("allowed_actions")
                                != ["read", "report"]
                            ):
                                problems.append(
                                    f"setup {width} {theme}: human fields did not create "
                                    "an inert read-only plan"
                                )
                            else:
                                page.get_by_role(
                                    "heading", name="https://owned.example", exact=True
                                ).wait_for()
                    problems.extend(f"{width} {theme}: {error}" for error in errors)
                    context.close()
            browser.close()
    finally:
        human_closed.set()
        human_worker.join(timeout=5)
        running.should_exit = True
        thread.join(timeout=20)
    (output / "problems.json").write_text(json.dumps(problems, indent=1), encoding="utf-8")
    print(f"{len(pages) * 4} pictures in {output}; {len(problems)} problem(s)")
    for problem in problems:
        print("  " + problem)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
