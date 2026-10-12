"""Current software packets use temporary pins; archived evaluation stays frozen."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from eval.mutation import development as corpus


@pytest.fixture(scope="module")
def current_development_manifest(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A software-only preparation, never a replacement or fresh quality result.

    Dependency additions can invalidate old generator metadata even when all
    development packets are identical. Keep production's refusal and both
    archives; explicitly pin current software inputs in a new temporary file.
    """
    archived, legacy = corpus.MANIFEST, corpus.LEGACY_MANIFEST
    original, original_legacy = archived.read_bytes(), legacy.read_bytes()
    current = corpus.manifest_for(corpus.make_cases())
    assert current["cases"] == json.loads(original)["cases"]
    assert current["base_manifest_sha256"] == corpus.sha(original_legacy)
    path = tmp_path_factory.mktemp("software-packets") / "development.json"
    path.write_text(json.dumps(current), encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(corpus, "MANIFEST", path)
        yield path
    assert archived.read_bytes() == original
    assert legacy.read_bytes() == original_legacy
