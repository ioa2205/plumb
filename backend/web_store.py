"""Private storage for website journeys, outside the repository (ADR-0028).

One JSON record per journey, replaced atomically at every checkpoint. A record
is refused if it would store anything the redactor recognizes as a secret.
Session state (cookies, storage) is kept in this process's memory and, when the
operating system offers per-user protection, in a protected file beside the
record; it is never part of the record and never readable as plain text.
"""

import ctypes
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from analysis.paths import is_link
from backend.contracts.web_journey import JourneyView
from backend.redaction import Redactor
from backend.settings import Settings

MAX_RECORD = 8 * 1024 * 1024
_JOURNEY = re.compile(r"journey-[0-9a-f]{32}")
# Sessions of journeys running in this process: journey -> account -> browser state.
_SESSIONS: dict[str, dict[str, dict[str, Any]]] = {}


# One process reads a record while another thread of it replaces the file.
_FILES = threading.RLock()


def replace_atomically(temporary: Path, target: Path) -> None:
    """Put the finished file in place; a reader sees the whole old or the whole new one.

    On Windows a reader that has the old file open can briefly deny its replacement.
    Only that moment is retried, at most eight times ten milliseconds apart; the
    complete old record stays readable meanwhile, and a lasting denial is raised.
    """
    try:
        for attempt in range(8):
            try:
                temporary.replace(target)
                return
            except PermissionError as error:
                transient = sys.platform == "win32" and getattr(error, "winerror", None) in {
                    5,
                    32,
                    33,
                }
                if not transient or attempt == 7:
                    raise
                time.sleep(0.01)
    finally:
        temporary.unlink(missing_ok=True)


class _Blob(ctypes.Structure):
    _fields_ = (("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_char)))


def _protect(data: bytes, *, undo: bool = False) -> bytes | None:
    """Per-user protection by the operating system (Windows DPAPI). None when unavailable."""
    if sys.platform != "win32":
        return None
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = _Blob()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    call = crypt32.CryptUnprotectData if undo else crypt32.CryptProtectData
    # 0x1: never show a prompt.
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)):
        return None
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


class JourneyStore:
    def __init__(self, settings: Settings) -> None:
        repository = Path(__file__).resolve().parents[1]
        base = settings.data_dir.resolve()
        if base == repository or repository in base.parents:
            raise ValueError("Private website data must live outside the repository")
        self.settings = settings
        self.directory = base / "websites"

    def folder(self, journey_id: str) -> Path:
        if _JOURNEY.fullmatch(journey_id) is None:
            raise ValueError("Invalid journey ID")
        folder = self.directory / journey_id
        for current in (folder, self.directory, *self.directory.parents):
            if current.exists() and is_link(current.lstat()):
                raise ValueError("Linked private storage refused")
        return folder

    def save(self, view: JourneyView, *, secrets: tuple[str, ...] = ()) -> None:
        folder = self.folder(view.journey_id)
        payload = view.model_dump(mode="json")
        text = json.dumps(payload, ensure_ascii=False, indent=1)
        redactor = Redactor.configured(self.settings, extra=tuple(s for s in secrets if s))
        if redactor.text(text) != text:
            raise ValueError("A journey record may not contain a secret; nothing was saved")
        if len(text.encode("utf-8")) > MAX_RECORD:
            raise ValueError("The journey record exceeds its storage bound")
        with _FILES:
            folder.mkdir(parents=True, exist_ok=True)
            temporary = folder / (uuid4().hex + ".tmp")
            temporary.write_text(text, encoding="utf-8", newline="\n")
            replace_atomically(temporary, folder / "journey.json")

    def load(self, journey_id: str) -> JourneyView:
        path = self.folder(journey_id) / "journey.json"
        with _FILES:
            if path.stat().st_size > MAX_RECORD:
                raise ValueError("The journey record exceeds its storage bound")
            raw = path.read_bytes()
        view = JourneyView.model_validate_json(raw)
        if view.journey_id != journey_id:
            raise ValueError("Journey identity differs")
        return view

    def list(self, limit: int = 20) -> list[JourneyView]:
        found: list[JourneyView] = []
        if not self.directory.is_dir():
            return found
        folders = sorted(
            (item for item in self.directory.iterdir() if _JOURNEY.fullmatch(item.name)),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for folder in folders[:limit]:
            try:
                found.append(self.load(folder.name))
            except (OSError, ValueError):
                continue
        return found

    # --- session state: memory first, protected file when the system can protect it ----------

    def keep_session(self, journey_id: str, account_id: str, state: dict[str, Any]) -> bool:
        """Remember one account's browser state. True when it also survives a restart."""
        _SESSIONS.setdefault(journey_id, {})[account_id] = state
        protected = _protect(json.dumps(state).encode("utf-8"))
        if protected is None:
            return False
        folder = self.folder(journey_id) / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", account_id) is None:
            return False
        (folder / (account_id.replace(":", "_") + ".bin")).write_bytes(protected)
        return True

    def session(self, journey_id: str, account_id: str) -> dict[str, Any] | None:
        """The remembered state, or None: then the account must sign in again. Never guessed."""
        state = _SESSIONS.get(journey_id, {}).get(account_id)
        if state is not None:
            return state
        path = self.folder(journey_id) / "sessions" / (account_id.replace(":", "_") + ".bin")
        try:
            plain = _protect(path.read_bytes(), undo=True)
            value = json.loads(plain) if plain is not None else None
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def forget_sessions(self, journey_id: str) -> None:
        _SESSIONS.pop(journey_id, None)
        folder = self.folder(journey_id) / "sessions"
        if folder.is_dir():
            for item in folder.iterdir():
                if item.suffix == ".bin":
                    item.unlink(missing_ok=True)

    def forget_session(self, journey_id: str, account_id: str) -> None:
        """Discard only this Plumb-owned account's protected interim state."""
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", account_id) is None:
            raise ValueError("Invalid account ID")
        _SESSIONS.get(journey_id, {}).pop(account_id, None)
        path = self.folder(journey_id) / "sessions" / (account_id.replace(":", "_") + ".bin")
        path.unlink(missing_ok=True)
