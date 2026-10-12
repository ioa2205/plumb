"""Canonical addresses: anything ambiguous is refused, never repaired."""

import pytest

from backend.web_urls import UrlRefused, parse_origin, parse_url, path_within


def test_a_plain_address_is_parsed_into_its_exact_parts() -> None:
    url = parse_url("https://Shop.Example.com/orders/41?id=7&x=a%20b#top")
    assert (url.scheme, url.host, url.port) == ("https", "shop.example.com", 443)
    assert (url.path, url.query) == ("/orders/41", "id=7&x=a%20b")
    assert url.origin == "https://shop.example.com"
    assert url.url == "https://shop.example.com/orders/41?id=7&x=a%20b"
    assert parse_url("http://127.0.0.1:8711").url == "http://127.0.0.1:8711/"
    assert parse_url("http://[2606:4700::1111]:8080/a").authority == "[2606:4700::1111]:8080"
    assert parse_url("https://shop.example.com:443/").origin == "https://shop.example.com"


@pytest.mark.parametrize(
    "address",
    [
        "",
        "shop.example.com",
        "ftp://shop.example.com/",
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "https://user:pass@shop.example.com/",
        "https://shop.example.com@evil.example/",
        "https://shop.example.com\\@evil.example/",
        "https://shop.example.com/a b",
        "https://shop.example.com/\x00",
        " https://shop.example.com/",
        "https://shop.example.com/\n",
        "https:///path",
        "https://shop.example.com:0/",
        "https://shop.example.com:99999/",
        "https://shop.example.com:08/",
        "https://shop.example.com:/",
        "https://shop.example.com./",
        "https://shop..example.com/",
        "https://-shop.example.com/",
        "https://shop_x.example.com/",
        "https://магазин.example/",
        # Numeric hosts that some parsers read as loopback and others as names.
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f.0.0.1/",
        "http://0177.0.0.1/",
        "http://127.0.0.01/",
        "http://[::ffff:7f00:1/",
        "http://[fe80::1%25eth0]/",
        "http://[0:0:0:0:0:0:0:1]/",
        # Paths that change under normalization.
        "https://shop.example.com/a/../admin",
        "https://shop.example.com/a/./b",
        "https://shop.example.com//admin",
        "https://shop.example.com/a%2f..%2fadmin",
        "https://shop.example.com/a%5cb",
        "https://shop.example.com/%2e%2e/admin",
        "https://shop.example.com/a%252fb",
        "https://shop.example.com/a%zz",
        "https://shop.example.com/a%",
        "https://shop.example.com/a?b=%0d%0aSet-Cookie:x",
        "https://shop.example.com/" + "a" * 2100,
    ],
)
def test_malformed_or_ambiguous_addresses_are_refused(address: str) -> None:
    with pytest.raises(UrlRefused):
        parse_url(address)


def test_an_origin_is_exactly_scheme_host_and_port() -> None:
    assert parse_origin("https://shop.example.com").origin == "https://shop.example.com"
    assert parse_origin("http://127.0.0.1:8711/").origin == "http://127.0.0.1:8711"
    for wrong in (
        "https://shop.example.com/orders",
        "https://shop.example.com/?a=1",
        "https://Shop.example.com",
        "https://shop.example.com:443",
        "shop.example.com",
    ):
        with pytest.raises(UrlRefused):
            parse_origin(wrong)


def test_path_prefixes_match_whole_segments_only() -> None:
    assert path_within("/app/orders", "/app")
    assert path_within("/app", "/app") and path_within("/anything", "/")
    assert path_within("/app/", "/app/") and path_within("/app/x", "/app/")
    assert not path_within("/apple", "/app")
    assert not path_within("/ap", "/app")
