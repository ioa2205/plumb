"""Run the lab on loopback: ``uv run python -m tandir [--port 8701]``.

Binding to anything other than 127.0.0.1 is refused: this application is
deliberately vulnerable.
"""

import argparse

import uvicorn

from tandir.main import create_app
from tandir.seed import seed

LOOPBACK = "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Tandir lab on loopback")
    parser.add_argument("--port", type=int, default=8701)
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="create and seed the data directory (shared with the web lab), then exit",
    )
    args = parser.parse_args()
    app = create_app()
    with app.state.sessionmaker() as db:
        seed(db, app.state.settings)
    if args.seed_only:
        app.state.engine.dispose()
        return
    uvicorn.run(app, host=LOOPBACK, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
