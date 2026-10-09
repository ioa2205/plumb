"""Protections that only the fixed snapshot has (M1.3, ADR-0005).

Skipped on the vulnerable lab; run on the patched copy with TANDIR_VARIANT=fixed
(labs/tandir/fixed/snapshot.py check). Each test mirrors its route's lookalike.
"""

import pytest

pytestmark = pytest.mark.fixed_only


def test_receipt_is_scoped_to_its_owner(lab) -> None:
    assert lab.client.get("/orders/1/receipt", headers=lab.as_("alice")).status_code == 200
    response = lab.client.get("/orders/1/receipt", headers=lab.as_("bob"))
    assert response.status_code == 404
    assert "ALICE-MARKER" not in response.text


def test_menu_edits_are_scoped_to_the_managers_branch(lab) -> None:
    body = {"name": "Non (large)", "price_cents": 700, "available": True}
    refused = lab.client.put("/branches/2/menu/3", json=body, headers=lab.as_("farrukh"))
    assert refused.status_code == 403
    menu = lab.client.get("/branches/2/menu").json()
    assert {i["name"] for i in menu} == {"Non", "Medovik cake"}
    allowed = lab.client.put("/branches/2/menu/3", json=body, headers=lab.as_("nodira"))
    assert allowed.status_code == 200


@pytest.mark.parametrize(("sort", "ids"), [("created_at", [1, 2]), ("total", [1, 2])])
def test_order_search_sorts_by_an_allowed_key(lab, sort: str, ids: list[int]) -> None:
    rows = lab.client.get("/admin/orders", params={"sort": sort}, headers=lab.as_("admin"))
    assert rows.status_code == 200
    assert [r["id"] for r in rows.json()] == ids


def test_order_search_refuses_an_unknown_sort(lab) -> None:
    response = lab.client.get("/admin/orders", params={"sort": "phone"}, headers=lab.as_("admin"))
    assert response.status_code == 400


def test_label_printing_passes_an_argument_list(lab) -> None:
    response = lab.client.post("/kitchen/orders/1/items/2/label", headers=lab.as_("farrukh"))
    assert response.status_code == 200
    [(args, kwargs)] = lab.commands.calls
    assert args == ["tandir-label", "--order", "1", "--text", "Happy birthday, Dilnoza!"]
    assert not kwargs.get("shell")


def test_photo_download_stays_inside_the_orders_folder(lab) -> None:
    files = {"file": ("cake.png", b"\x89PNG bob photo", "image/png")}
    upload = lab.client.post("/orders/2/photos", files=files, headers=lab.as_("bob"))
    bobs_photo = upload.json()["filename"]
    response = lab.client.get(
        "/orders/1/photos", params={"name": f"../2/{bobs_photo}"}, headers=lab.as_("alice")
    )
    assert response.status_code == 404
    own = lab.client.get(
        "/orders/1/photos", params={"name": "reference.jpg"}, headers=lab.as_("alice")
    )
    assert own.status_code == 200
