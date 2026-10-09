"""The symbol index: tree-sitter facts in SQLite with FTS5 search (task M2.2).

One index per snapshot, built from the snapshot store (never the live tree) and
kept at ``<cache>/index/<snapshot id>.sqlite``. It holds files, symbols, and
imports, plus a full-text table over symbol names (also split into words, so
``getOrderDTO`` is found by "order dto"), qualified names, paths, and bodies.
"""

import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any

from analysis.snapshot import SnapshotStore
from analysis.syntax import FileFacts, extract, span_sha256, words
from backend.contracts.code import ProjectSnapshot, SourceSpan, Symbol, SymbolKind
from backend.contracts.common import Language

SCHEMA_VERSION = "1"


def extractor_identity() -> str:
    return hashlib.sha256(
        Path(__file__).read_bytes() + Path(__file__).with_name("syntax.py").read_bytes()
    ).hexdigest()


BODY_CHARS = 4000  # of each symbol's text kept for full-text search
_BODY_KINDS = ("function", "method", "class", "component")

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    language TEXT NOT NULL,
    module TEXT NOT NULL,
    directive TEXT,
    lines INTEGER NOT NULL,
    has_errors INTEGER NOT NULL
);
CREATE TABLE symbols (
    rid INTEGER PRIMARY KEY,
    id TEXT UNIQUE NOT NULL,
    path TEXT NOT NULL REFERENCES files(path),
    name TEXT NOT NULL,
    local_name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    language TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    parent TEXT,
    exported INTEGER NOT NULL,
    is_default INTEGER NOT NULL,
    is_async INTEGER NOT NULL,
    decorators TEXT NOT NULL,
    directive TEXT,
    content_sha256 TEXT NOT NULL
);
CREATE INDEX symbols_path ON symbols(path);
CREATE INDEX symbols_name ON symbols(name);
CREATE INDEX symbols_qualified ON symbols(qualified_name);
CREATE TABLE imports (
    path TEXT NOT NULL REFERENCES files(path),
    line INTEGER NOT NULL,
    module TEXT NOT NULL,
    name TEXT,
    alias TEXT,
    level INTEGER NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX imports_path ON imports(path);
CREATE VIRTUAL TABLE search USING fts5(name, words, qualified, path, body);
"""

_INSERT_SYMBOL = """
INSERT INTO symbols (id, path, name, local_name, qualified_name, kind, language, start_line,
                     end_line, parent, exported, is_default, is_async, decorators, directive,
                     content_sha256)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_SELECT_SYMBOLS = """
SELECT id, path, name, local_name, qualified_name, kind, language, start_line, end_line,
       parent, exported, is_default, is_async, decorators, directive, content_sha256
  FROM symbols
 WHERE (? IS NULL OR path = ?) AND (? IS NULL OR kind = ?)
 ORDER BY path, start_line, local_name
"""
_SELECT_QUALIFIED = """
SELECT id, path, name, local_name, qualified_name, kind, language, start_line, end_line,
       parent, exported, is_default, is_async, decorators, directive, content_sha256
  FROM symbols
 WHERE qualified_name = ?
 ORDER BY start_line
"""
_SELECT_IMPORTS = """
SELECT path, line, module, name, alias, level, kind
  FROM imports
 WHERE (? IS NULL OR path = ?)
 ORDER BY path, line
"""
# Free text is passed as a quoted FTS5 query parameter; kinds as a JSON array ("[]" = any).
_SEARCH = """
SELECT s.id, s.path, s.name, s.local_name, s.qualified_name, s.kind, s.language, s.start_line,
       s.end_line, s.parent, s.exported, s.is_default, s.is_async, s.decorators, s.directive,
       s.content_sha256
  FROM search JOIN symbols s ON s.rid = search.rowid
 WHERE search MATCH ?
   AND (? = '[]' OR s.kind IN (SELECT value FROM json_each(?)))
 -- bm25 is negative (lower is better): a module ranks just below a symbol of the same name
 ORDER BY bm25(search, 10.0, 6.0, 3.0, 1.0, 0.5)
          * (CASE s.kind WHEN 'module' THEN 0.8 ELSE 1.0 END),
          s.path
 LIMIT ?
"""


@dataclass(frozen=True)
class SymbolRow:
    id: str
    path: str
    name: str
    local_name: str
    qualified_name: str
    kind: SymbolKind
    language: Language
    start_line: int
    end_line: int
    parent: str | None
    exported: bool
    is_default: bool
    is_async: bool
    decorators: tuple[str, ...]
    directive: str | None
    content_sha256: str


@dataclass(frozen=True)
class ImportRow:
    path: str
    line: int
    module: str
    name: str | None
    alias: str | None
    level: int
    kind: str


def symbol_id(path: str, local_name: str, start_line: int) -> str:
    digest = hashlib.sha256(f"{path}\0{local_name}\0{start_line}".encode()).hexdigest()
    return f"sym:{digest[:24]}"


def qualified(facts: FileFacts, local_name: str) -> str:
    if not local_name:
        return facts.module
    separator = "." if facts.language is Language.PYTHON else ":"
    return f"{facts.module}{separator}{local_name}"


def _package_dirs(snapshot: ProjectSnapshot) -> set[str]:
    return {
        PurePosixPath(f.path).parent.as_posix()
        for f in snapshot.files
        if PurePosixPath(f.path).name == "__init__.py"
    }


def _parser_versions() -> str:
    packages = ("tree-sitter", "tree-sitter-python", "tree-sitter-typescript")
    return ", ".join(f"{p} {version(p)}" for p in packages)


def _fts_query(text: str, operator: str) -> str | None:
    """User text as a safe FTS5 query: quoted word prefixes, never raw syntax."""
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_]+", text):
        for word in words(raw).split() or [raw.lower()]:
            if word not in tokens:
                tokens.append(word)
    if not tokens:
        return None
    return f" {operator} ".join(f'"{t}"*' for t in tokens)


class Index:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.db = connection

    # building ---------------------------------------------------------------------------------

    @classmethod
    def build(cls, snapshot: ProjectSnapshot, store: SnapshotStore, path: Path) -> "Index":
        """Build (or reopen, when already built for this snapshot) the index at ``path``."""
        if path.exists():
            existing = cls.open(path)
            if (
                existing.meta("snapshot_id") == snapshot.id
                and existing.meta("schema_version") == SCHEMA_VERSION
                and existing.meta("parsers") == _parser_versions()
                and existing.meta("extractor_sha256") == extractor_identity()
            ):
                return existing
            existing.close()
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.part")
        temporary.unlink(missing_ok=True)
        db = sqlite3.connect(temporary)
        db.executescript(_SCHEMA)
        packages = _package_dirs(snapshot)
        with db:
            for file in snapshot.files:
                if file.language is None:
                    continue
                source = store.read(snapshot, file.path)
                facts = extract(file.path, file.language, source, packages)
                cls._insert(db, facts, file.sha256, source)
            meta = {
                "snapshot_id": snapshot.id,
                "schema_version": SCHEMA_VERSION,
                "parsers": _parser_versions(),
                "extractor_sha256": extractor_identity(),
            }
            db.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
        db.close()
        temporary.replace(path)
        return cls.open(path)

    @staticmethod
    def _insert(db: sqlite3.Connection, facts: FileFacts, sha256: str, source: bytes) -> None:
        db.execute(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?)",
            (facts.path, sha256, facts.language.value, facts.module, facts.directive,
             facts.lines, int(facts.has_errors)),
        )  # fmt: skip
        lines = source.decode("utf-8", errors="replace").split("\n")
        for s in facts.symbols:
            name = qualified(facts, s.local_name)
            cursor = db.execute(
                _INSERT_SYMBOL,
                (symbol_id(facts.path, s.local_name, s.start_line), facts.path, s.name,
                 s.local_name, name, s.kind.value, facts.language.value, s.start_line,
                 s.end_line, s.parent, int(s.exported), int(s.is_default), int(s.is_async),
                 "\n".join(s.decorators), s.directive,
                 span_sha256(source, s.start_line, s.end_line)),
            )  # fmt: skip
            body = ""
            if s.kind.value in _BODY_KINDS:
                body = "\n".join(lines[s.start_line - 1 : s.end_line])[:BODY_CHARS]
            db.execute(
                "INSERT INTO search (rowid, name, words, qualified, path, body)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (cursor.lastrowid, s.name, words(s.name), name, facts.path, body),
            )
        db.executemany(
            "INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(facts.path, i.line, i.module, i.name, i.alias, i.level, i.kind)
             for i in facts.imports],
        )  # fmt: skip

    # reading -----------------------------------------------------------------------------------

    @classmethod
    def open(cls, path: Path) -> "Index":
        if not path.is_file():
            raise FileNotFoundError(path)
        return cls(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True))

    def close(self) -> None:
        self.db.close()

    def meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _row(r: tuple[Any, ...]) -> SymbolRow:
        return SymbolRow(
            id=r[0], path=r[1], name=r[2], local_name=r[3], qualified_name=r[4],
            kind=SymbolKind(r[5]), language=Language(r[6]), start_line=r[7], end_line=r[8],
            parent=r[9], exported=bool(r[10]), is_default=bool(r[11]), is_async=bool(r[12]),
            decorators=tuple(r[13].split("\n")) if r[13] else (), directive=r[14],
            content_sha256=r[15],
        )  # fmt: skip

    def symbols(self, path: str | None = None, kind: SymbolKind | None = None) -> list[SymbolRow]:
        kind_value = kind.value if kind else None
        rows = self.db.execute(_SELECT_SYMBOLS, (path, path, kind_value, kind_value))
        return [self._row(r) for r in rows]

    def symbol(self, qualified_name: str) -> SymbolRow | None:
        row = self.db.execute(_SELECT_QUALIFIED, (qualified_name,)).fetchone()
        return self._row(row) if row else None

    def imports(self, path: str | None = None) -> list[ImportRow]:
        return [ImportRow(*r) for r in self.db.execute(_SELECT_IMPORTS, (path, path))]

    def file_directive(self, path: str) -> str | None:
        row = self.db.execute("SELECT directive FROM files WHERE path = ?", (path,)).fetchone()
        return row[0] if row else None

    def counts(self) -> dict[str, int]:
        return dict(Counter(kind for (kind,) in self.db.execute("SELECT kind FROM symbols")))

    def search(
        self, text: str, limit: int = 10, kinds: tuple[SymbolKind, ...] = ()
    ) -> list[SymbolRow]:
        """Ranked symbols for free text: all words first, any word if nothing matches."""
        for operator in ("AND", "OR"):
            query = _fts_query(text, operator)
            if query is None:
                return []
            wanted = json.dumps([k.value for k in kinds])
            rows = self.db.execute(_SEARCH, (query, wanted, wanted, limit)).fetchall()
            if rows:
                return [self._row(r) for r in rows]
        return []

    def to_contract(self, row: SymbolRow, snapshot_id: str) -> Symbol:
        return Symbol(
            id=row.id,
            snapshot_id=snapshot_id,
            name=row.name or row.qualified_name,
            qualified_name=row.qualified_name,
            kind=row.kind,
            language=row.language,
            span=SourceSpan(
                snapshot_id=snapshot_id,
                path=row.path,
                start_line=row.start_line,
                end_line=row.end_line,
                content_sha256=row.content_sha256,
            ),
        )


def index_path(cache_dir: Path, snapshot_id: str) -> Path:
    return cache_dir / "index" / f"{snapshot_id}.sqlite"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from analysis.snapshot import take_snapshot
    from backend.settings import Settings
    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(description="Snapshot and index a project folder.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--search", action="append", default=[], help="free-text symbol search")
    args = parser.parse_args(argv)
    cache = Settings().cache_dir
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    print(f"snapshot {snapshot.id[:16]}, parsers: {index.meta('parsers')}")
    print(f"symbols: {index.counts()}")
    for text in args.search:
        print(f"search {text!r}:")
        for row in index.search(text, limit=5):
            print(f"  {row.kind.value:9} {row.qualified_name}  ({row.path}:{row.start_line})")
    index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
