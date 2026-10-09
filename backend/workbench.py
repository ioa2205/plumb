"""Serve only the trusted, build-manifested workbench. Never serve project files."""

import base64
import hashlib
import json
import os
import re
import stat
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import Receive, Scope, Send

from analysis.paths import check_relative, is_link, resolve_inside
from analysis.snapshot import ChangedWhileReadingError, read_contained
from backend.contracts.common import Sha256
from backend.security import CSP_SCRIPT_HASHES

DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "frontend" / "out"
MANIFEST_NAME = "plumb-export.json"
MAX_FILE_BYTES = 8 * 1024**2
MAX_MANIFEST_BYTES = 1024**2
NOT_BUILT = "The workbench is not built. Build the frontend, then restart Plumb."
UNAVAILABLE = "The workbench export cannot be verified. Rebuild it, then restart Plumb."
MEDIA = {
    ".html": "text/html",
    ".txt": "text/plain",
    ".js": "text/javascript",
    ".css": "text/css",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".json": "application/json",
}
ScriptHash = Annotated[str, Field(pattern=r"^sha256-[A-Za-z0-9+/]{43}=$")]


class ExportFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    sha256: Sha256
    bytes: int = Field(ge=0, le=MAX_FILE_BYTES)
    script_hashes: list[ScriptHash] = Field(max_length=64)


class ExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal[1]
    files: dict[str, ExportFile] = Field(min_length=1, max_length=4096)

    @field_validator("files")
    @classmethod
    def safe_files(cls, files: dict[str, ExportFile]) -> dict[str, ExportFile]:
        folded: set[str] = set()
        for name, item in files.items():
            path = check_relative(name)
            if (
                str(path) != name
                or re.fullmatch(r"[A-Za-z0-9_./-]+", name) is None
                or any(part.startswith(".") for part in path.parts)
                or path.parts[0] in {"api", "bootstrap", "404", "_not-found"}
                or name in {MANIFEST_NAME, "404.html", "openapi.json"}
                or path.suffix not in MEDIA
                or name.casefold() in folded
            ):
                raise ValueError("invalid export file name")
            if path.suffix != ".html" and item.script_hashes:
                raise ValueError("script hashes belong only to HTML documents")
            folded.add(name.casefold())
        return files


class ExportError(ValueError):
    pass


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.hashes: set[str] = set()
        self._text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "style" or any(name == "style" or name.startswith("on") for name, _ in attrs):
            raise ExportError("inline styles/events are not allowed")
        if tag == "script":
            if self._text is not None:
                raise ExportError("nested script")
            source = dict(attrs).get("src")
            if source is not None:
                if not source.startswith("/_next/static/"):
                    raise ExportError("unexpected script source")
                check_relative(source[1:])
            else:
                self._text = []

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._text is not None:
            content = "".join(self._text).encode("utf-8")
            self.hashes.add("sha256-" + base64.b64encode(hashlib.sha256(content).digest()).decode())
            self._text = None

    def finish(self, data: bytes) -> tuple[str, ...]:
        self.feed(data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"))
        self.close()
        if self._text is not None:
            raise ExportError("unfinished script")
        return tuple(sorted(self.hashes))


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ExportError("duplicate manifest field")
        result[name] = value
    return result


class Workbench:
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Router fallback, so even API routes registered later retain precedence."""
        request = Request(scope)
        path = scope["path"].removeprefix("/")
        if path == "api" or path.startswith("api/"):
            response = PlainTextResponse("Not found.", status_code=404)
        elif request.method not in {"GET", "HEAD"}:
            response = PlainTextResponse(
                "Method not allowed.", status_code=405, headers={"Allow": "GET, HEAD"}
            )
        else:
            response = await run_in_threadpool(self.response, request, path)
        await response(scope, receive, send)

    def __init__(self, directory: Path) -> None:
        self.directory = directory.absolute()
        self.manifest: ExportManifest | None = None
        self.unavailable = False
        try:
            raw = self._read(MANIFEST_NAME, MAX_MANIFEST_BYTES)
        except FileNotFoundError:
            return
        except (OSError, ValueError, ChangedWhileReadingError):
            self.unavailable = True
            return
        try:
            self.manifest = ExportManifest.model_validate(
                json.loads(raw, object_pairs_hook=_unique)
            )
        except (ValueError, UnicodeError, RecursionError):
            self.unavailable = True

    def _read(self, name: str, limit: int) -> bytes:
        # Do not canonicalize through a substituted root/ancestor link.
        if is_link(self.directory.lstat()) or os.path.normcase(
            self.directory.resolve(strict=True)
        ) != os.path.normcase(self.directory):
            raise ExportError("export root is a link")
        path = resolve_inside(self.directory, name)
        expected = path.lstat()
        if not stat.S_ISREG(expected.st_mode) or expected.st_size > limit:
            raise ExportError("export file fails type/size limit")
        data = read_contained(path, expected, limit)
        if data is None:
            raise ExportError("export file grew beyond limit")
        return data

    def response(self, request: Request, path: str) -> Response:
        if path.startswith("api/") or path in {"api", "bootstrap", MANIFEST_NAME, "openapi.json"}:
            return PlainTextResponse("Not found.", status_code=404)
        if self.unavailable:
            return PlainTextResponse(UNAVAILABLE, status_code=503)
        if self.manifest is None:
            return PlainTextResponse(NOT_BUILT, status_code=404)
        name = path if path in self.manifest.files else path.rstrip("/") + "/index.html"
        if path == "":
            name = "index.html"
        item = self.manifest.files.get(name)
        if item is None:
            return PlainTextResponse("Not found.", status_code=404)
        try:
            data = self._read(name, MAX_FILE_BYTES)
            if len(data) != item.bytes or hashlib.sha256(data).hexdigest() != item.sha256:
                raise ExportError("export changed")
            if name.endswith(".html"):
                hashes = _Scripts().finish(data)
                if hashes != tuple(sorted(set(item.script_hashes))):
                    raise ExportError("export script hashes differ")
                request.scope[CSP_SCRIPT_HASHES] = hashes
        except (OSError, ValueError, ChangedWhileReadingError):
            return PlainTextResponse(UNAVAILABLE, status_code=503)
        response = Response(data, media_type=MEDIA[Path(name).suffix])
        if request.method == "HEAD":
            response.body = b""
        return response
