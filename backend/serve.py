"""Start the local API on loopback and print the one-time link that opens it.

uv run python -m backend.serve
"""

import socket
import sys
import webbrowser

import uvicorn
from fastapi import FastAPI

from backend.app import create_app
from backend.security import LOOPBACK
from backend.settings import Settings
from backend.system_tools import unsupported_system


def bind(port: int) -> socket.socket:
    """A listening socket on loopback only; ``port`` 0 lets the system choose one."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        # Without this, another process could bind the same port and take the requests.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind((LOOPBACK, port))
    except OSError:
        listener.close()
        raise
    return listener


class BrowserServer(uvicorn.Server):
    """Open the ordinary bootstrap link only after loopback is listening."""

    def __init__(self, config: uvicorn.Config, link: str) -> None:
        super().__init__(config)
        self.link = link

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            try:
                opened = webbrowser.open(self.link)
            except webbrowser.Error:
                opened = False
            if not opened:
                print("Browser did not open. Use the printed one-time link.", flush=True)


def server(
    listener: socket.socket, settings: Settings | None = None, *, open_browser: bool = False
) -> tuple[uvicorn.Server, FastAPI]:
    """A server for an already bound loopback socket, and its app. Requests are not logged."""
    address, port = listener.getsockname()
    if address != LOOPBACK:
        raise ValueError("Plumb serves on loopback only")
    app = create_app(settings, port=port)
    config = uvicorn.Config(
        app,
        access_log=False,  # a request line would put the bootstrap token in a log
        server_header=False,
        proxy_headers=False,  # no proxy sits in front, so forwarded headers are never trusted
        log_level="warning",
    )
    running = (
        BrowserServer(config, app.state.gate.bootstrap_url)
        if open_browser
        else uvicorn.Server(config)
    )
    return running, app


def main(*, open_browser: bool = False) -> int:
    if refusal := unsupported_system():
        print(refusal)
        return 1
    try:
        settings = Settings()
    except (OSError, ValueError):
        print(
            "Cannot read Plumb settings. Check PLUMB_* values or run plumb setup --data-dir "
            "<absolute-external-folder>. Existing preferences were preserved."
        )
        return 1
    try:
        listener = bind(settings.port)
    except OSError:
        print(
            f"Cannot start Plumb on local port {settings.port}. "
            "Close the existing Plumb server or set PLUMB_PORT."
        )
        return 1
    with listener:
        running, app = server(listener, settings, open_browser=open_browser)
        # Printed once, for the person at this terminal. It is not written to any log.
        link = app.state.gate.bootstrap_url
        print(f"Plumb is running. Open this link once: {link}", flush=True)
        print("Stop with Ctrl+C. Opening the workbench does not start a model.", flush=True)
        running.run(sockets=[listener])
    return 0


if __name__ == "__main__":
    sys.exit(main())
