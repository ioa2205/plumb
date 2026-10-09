"""Customer order routes: legitimate use, and the protections that must hold."""

import pytest

from tandir.seed import ALICE_ADDRESS, BOB_ADDRESS

ALICE_ORDER = 1
BOB_ORDER = 2

# Routes guarded by ownership, each in a different form: a query filter, a
# scoped loader in another file, an inline comparison, a dependency, and a
# helper called after the load.
OWNED_ROUTES = [
    ("get", "/orders/{id}"),
    ("get", "/orders/{id}/invoice"),
    ("get", "/orders/{id}/items"),
    ("get", "/orders/{id}/tracking"),
]


def test_customers_list_only_their_own_orders(lab) -> None:
    alice = lab.client.get("/orders", headers=lab.as_("alice")).json()
    bob = lab.client.get("/orders", headers=lab.as_("bob")).json()
    assert [o["id"] for o in alice] == [ALICE_ORDER]
    assert [o["id"] for o in bob] == [BOB_ORDER]


@pytest.mark.parametrize(("method", "route"), OWNED_ROUTES)
def test_owner_reads_their_order(lab, method: str, route: str) -> None:
    response = lab.client.request(method, route.format(id=ALICE_ORDER), headers=lab.as_("alice"))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(("method", "route"), OWNED_ROUTES)
def test_another_customers_order_is_not_found(lab, method: str, route: str) -> None:
    response = lab.client.request(method, route.format(id=ALICE_ORDER), headers=lab.as_("bob"))
    assert response.status_code == 404
    assert "ALICE-MARKER" not in response.text


@pytest.mark.parametrize(("method", "route"), OWNED_ROUTES)
def test_missing_order_is_not_found(lab, method: str, route: str) -> None:
    response = lab.client.request(method, route.format(id=999), headers=lab.as_("alice"))
    assert response.status_code == 404


def test_invoice_carries_the_owners_details(lab) -> None:
    invoice = lab.client.get(f"/orders/{ALICE_ORDER}/invoice", headers=lab.as_("alice")).json()
    assert invoice["delivery_address"] == ALICE_ADDRESS
    assert invoice["invoice_number"] == "TND-000001"
    assert invoice["total_cents"] == sum(
        i["unit_price_cents"] * i["quantity"] for i in invoice["items"]
    )


def test_owner_reads_their_receipt(lab) -> None:
    receipt = lab.client.get(f"/orders/{BOB_ORDER}/receipt", headers=lab.as_("bob"))
    assert receipt.status_code == 200
    assert receipt.json()["delivery_address"] == BOB_ADDRESS


def test_placing_an_order_prices_it_on_the_server(lab) -> None:
    body = {
        "branch_id": 1,
        "delivery_address": "1 Test Street",
        "items": [
            {"menu_item_id": 1, "quantity": 3},
            {"menu_item_id": 2, "quantity": 1, "inscription": "Tabriklaymiz!"},
        ],
    }
    response = lab.client.post("/orders", json=body, headers=lab.as_("bob"))
    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "placed"
    assert order["total_cents"] == 3 * 900 + 24000
    listed = lab.client.get("/orders", headers=lab.as_("bob")).json()
    assert order["id"] in [o["id"] for o in listed]


def test_items_from_another_branch_are_refused(lab) -> None:
    body = {"branch_id": 1, "delivery_address": "x", "items": [{"menu_item_id": 3, "quantity": 1}]}
    assert lab.client.post("/orders", json=body, headers=lab.as_("bob")).status_code == 422


def test_owner_cancels_their_order_once(lab) -> None:
    first = lab.client.post(f"/orders/{ALICE_ORDER}/cancel", headers=lab.as_("alice"))
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    again = lab.client.post(f"/orders/{ALICE_ORDER}/cancel", headers=lab.as_("alice"))
    assert again.status_code == 409


def test_another_customer_cannot_cancel(lab) -> None:
    response = lab.client.post(f"/orders/{ALICE_ORDER}/cancel", headers=lab.as_("bob"))
    assert response.status_code == 404
    status = lab.client.get(f"/orders/{ALICE_ORDER}", headers=lab.as_("alice")).json()["status"]
    assert status == "baking"


def _upload(lab, username: str, order_id: int, content_type: str = "image/png"):
    files = {"file": ("cake.png", b"\x89PNG test photo", content_type)}
    return lab.client.post(f"/orders/{order_id}/photos", files=files, headers=lab.as_(username))


def test_owner_uploads_and_downloads_a_photo(lab) -> None:
    uploaded = _upload(lab, "alice", ALICE_ORDER)
    assert uploaded.status_code == 201
    name = uploaded.json()["filename"]
    assert name.endswith(".png")
    assert name != "cake.png"
    photo = lab.client.get(
        f"/orders/{ALICE_ORDER}/photos", params={"name": name}, headers=lab.as_("alice")
    )
    assert photo.status_code == 200
    assert photo.content == b"\x89PNG test photo"


def test_seeded_reference_photo_downloads_for_its_owner(lab) -> None:
    photo = lab.client.get(
        f"/orders/{ALICE_ORDER}/photos",
        params={"name": "reference.jpg"},
        headers=lab.as_("alice"),
    )
    assert photo.status_code == 200


def test_photos_of_another_customers_order_are_not_found(lab) -> None:
    photo = lab.client.get(
        f"/orders/{ALICE_ORDER}/photos",
        params={"name": "reference.jpg"},
        headers=lab.as_("bob"),
    )
    assert photo.status_code == 404
    assert _upload(lab, "bob", ALICE_ORDER).status_code == 404


def test_upload_accepts_only_images(lab) -> None:
    assert _upload(lab, "alice", ALICE_ORDER, "text/html").status_code == 415
    assert _upload(lab, "alice", ALICE_ORDER, "application/octet-stream").status_code == 415
