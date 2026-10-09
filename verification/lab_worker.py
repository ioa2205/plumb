"""Trusted child: runs only the verified bundled API copy, with printing disabled."""

import hashlib
import json
import socket
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    if len(sys.argv) not in {3, 4}:
        raise ValueError("expected source, data and optional release variant")
    root, data = Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve()
    pin = json.loads((Path(__file__).parent / "pins/tandir-api.json").read_text())
    variant = sys.argv[3] if len(sys.argv) == 4 else "vulnerable"
    expected_files = dict(pin["files"])
    if variant != "vulnerable":
        if variant != "receipt_fixed":
            raise ValueError("unknown bundled release variant")
        expected_files.update(pin["variants"][variant]["files"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != pin["worker_sha256"]:
        raise ValueError("worker pin mismatch")
    if {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} != set(
        expected_files
    ):
        raise ValueError("source copy does not exactly match the pinned file set")
    for name, expected in expected_files.items():
        source = root / name
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("source copy hash mismatch")
    if data.parent != root.parent or data.name != "data" or data.exists():
        raise ValueError("data must be a fresh sibling directory")
    data.mkdir()
    sys.dont_write_bytecode = True
    # The parent copies only hash-pinned lab files here; arbitrary targets are never admitted.
    sys.path.insert(0, str(root))
    from tandir.config import Settings  # ty: ignore[unresolved-import]
    from tandir.main import create_app  # ty: ignore[unresolved-import]
    from tandir.seed import seed  # ty: ignore[unresolved-import]

    app = create_app(Settings(data_dir=data, printer_enabled=False))
    with app.state.sessionmaker() as db:
        seed(db, app.state.settings)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(("127.0.0.1", 0))
    print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
    try:
        uvicorn.Server(
            uvicorn.Config(
                app, log_level="error", access_log=False, proxy_headers=False, server_header=False
            )
        ).run(sockets=[listener])
    finally:
        listener.close()
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
