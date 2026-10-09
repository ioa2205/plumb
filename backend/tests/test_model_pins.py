from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.setup.pins import load_model_pins

GOOD_HASH = "0" * 64


def test_model_pins_load_with_the_main_track_first() -> None:
    pins = load_model_pins()
    assert pins.models[0].id == "qwen3.5-2b-q4_k_m"
    main = pins.get("qwen3.5-2b-q4_k_m")
    assert main.url.startswith("https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/")
    assert main.revision in main.url
    assert all(m.license for m in pins.models)


def test_unknown_model_id_is_a_key_error() -> None:
    with pytest.raises(KeyError, match="unknown model id"):
        load_model_pins().get("gpt-cloud")


def test_duplicate_model_ids_are_rejected(tmp_path: Path) -> None:
    entry = """
[[models]]
id = "dup"
family = "f"
role = "r"
repo = "a/b"
revision = "{rev}"
file = "m.gguf"
sha256 = "{sha}"
size = 1
quantization = "Q4_K_M"
license = "apache-2.0"
license_source = "card"
base_model = "a/b"
""".format(rev="a" * 40, sha=GOOD_HASH)
    path = tmp_path / "models.toml"
    path.write_text(entry * 2, encoding="utf-8")
    with pytest.raises(ValidationError, match="unique"):
        load_model_pins(path)
