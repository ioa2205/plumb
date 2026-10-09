import pytest
from pydantic import ValidationError

from backend.setup.pins import Asset, load_llama_cpp_pin

GOOD_HASH = "0" * 64


def test_llama_cpp_pin_loads_and_covers_cpu_and_cuda_12_4() -> None:
    pin = load_llama_cpp_pin()
    assert {"cpu", "cuda-12.4"} <= set(pin.variants)
    for variant in pin.variants.values():
        for asset in variant.assets:
            assert pin.build in asset.url
            assert "cuda-13" not in asset.name, "CUDA 13 builds do not run on the MX350"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b.zip",  # not https
        "https://github.com.evil.example/a/b.zip",  # lookalike host
        "https://example.com/a/b.zip",  # unlisted host
    ],
)
def test_asset_urls_must_be_https_on_github(url: str) -> None:
    with pytest.raises(ValidationError):
        Asset(name="b.zip", url=url, sha256=GOOD_HASH, size=1)


@pytest.mark.parametrize("name", ["../b.zip", "sub/b.zip", "b.zip\\..\\x"])
def test_asset_names_are_plain_file_names(name: str) -> None:
    with pytest.raises(ValidationError):
        Asset(name=name, url="https://github.com/a/b.zip", sha256=GOOD_HASH, size=1)
