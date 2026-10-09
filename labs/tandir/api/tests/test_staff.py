"""Branch, admin, courier, kitchen, and file routes: legitimate use and protections."""

import pytest

FARRUKH_BRANCH = 1
NODIRA_BRANCH = 2


# Branches


def test_menu_is_public(lab) -> None:
    menu = lab.client.get(f"/branches/{FARRUKH_BRANCH}/menu").json()
    assert {i["name"] for i in menu} == {"Samsa", "Napoleon cake"}


def test_manager_updates_their_own_menu(lab) -> None:
    body = {"name": "Samsa (lamb)", "price_cents": 1100, "available": True}
    response = lab.client.put(
        f"/branches/{FARRUKH_BRANCH}/menu/1", json=body, headers=lab.as_("farrukh")
    )
    assert response.status_code == 200
    assert response.json()["price_cents"] == 1100


def test_menu_item_must_belong_to_the_branch_in_the_path(lab) -> None:
    body = {"name": "x", "price_cents": 1, "available": True}
    response = lab.client.put(
        f"/branches/{FARRUKH_BRANCH}/menu/3", json=body, headers=lab.as_("farrukh")
    )
    assert response.status_code == 404


@pytest.mark.parametrize("username", ["alice", "kamol", "admin"])
def test_only_branch_managers_edit_menus(lab, username: str) -> None:
    body = {"name": "x", "price_cents": 1, "available": True}
    response = lab.client.put(
        f"/branches/{FARRUKH_BRANCH}/menu/1", json=body, headers=lab.as_(username)
    )
    assert response.status_code == 403


def test_manager_updates_their_own_hours(lab) -> None:
    body = {"opens_at": "06:30", "closes_at": "20:00"}
    response = lab.client.put(
        f"/branches/{FARRUKH_BRANCH}/hours", json=body, headers=lab.as_("farrukh")
    )
    assert response.status_code == 200
    assert response.json()["opens_at"] == "06:30"


def test_manager_cannot_change_another_branchs_hours(lab) -> None:
    body = {"opens_at": "06:30", "closes_at": "20:00"}
    response = lab.client.put(
        f"/branches/{NODIRA_BRANCH}/hours", json=body, headers=lab.as_("farrukh")
    )
    assert response.status_code == 403


def test_manager_sees_only_their_branchs_orders(lab) -> None:
    own = lab.client.get(f"/branches/{FARRUKH_BRANCH}/orders", headers=lab.as_("farrukh"))
    assert [o["id"] for o in own.json()] == [1]
    other = lab.client.get(f"/branches/{NODIRA_BRANCH}/orders", headers=lab.as_("farrukh"))
    assert other.status_code == 403


# Admin


def test_staff_search_orders_by_customer_name(lab) -> None:
    rows = lab.client.get("/admin/orders", params={"q": "Alice"}, headers=lab.as_("admin")).json()
    assert [r["id"] for r in rows] == [1]


@pytest.mark.parametrize("sort", ["name", "joined"])
def test_staff_search_customers_with_an_allowed_sort(lab, sort: str) -> None:
    rows = lab.client.get(
        "/admin/customers", params={"sort": sort}, headers=lab.as_("farrukh")
    ).json()
    assert {r["display_name"] for r in rows} == {"Alice Karimova", "Bob Tursunov"}


def test_customer_search_refuses_an_unknown_sort(lab) -> None:
    response = lab.client.get(
        "/admin/customers", params={"sort": "phone"}, headers=lab.as_("admin")
    )
    assert response.status_code == 400


def test_customer_search_treats_the_name_as_data(lab) -> None:
    response = lab.client.get(
        "/admin/customers", params={"name": "O'Brien"}, headers=lab.as_("admin")
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("route", ["/admin/orders", "/admin/customers"])
@pytest.mark.parametrize("username", ["alice", "kamol"])
def test_admin_search_is_staff_only(lab, route: str, username: str) -> None:
    assert lab.client.get(route, headers=lab.as_(username)).status_code == 403


def test_admin_reads_any_order(lab) -> None:
    assert lab.client.get("/admin/orders/2", headers=lab.as_("admin")).status_code == 200


@pytest.mark.parametrize("username", ["farrukh", "alice"])
def test_order_lookup_is_admin_only(lab, username: str) -> None:
    assert lab.client.get("/admin/orders/2", headers=lab.as_(username)).status_code == 403


# Courier


def test_courier_sees_their_deliveries(lab) -> None:
    deliveries = lab.client.get("/courier/deliveries", headers=lab.as_("kamol")).json()
    assert [d["order_id"] for d in deliveries] == [1]
    detail = lab.client.get("/courier/orders/1", headers=lab.as_("kamol")).json()
    assert set(detail) == {"order_id", "status", "delivery_address", "customer_name"}


def test_courier_cannot_read_an_unassigned_order(lab) -> None:
    assert lab.client.get("/courier/orders/2", headers=lab.as_("kamol")).status_code == 404


def test_courier_routes_are_courier_only(lab) -> None:
    assert lab.client.get("/courier/deliveries", headers=lab.as_("alice")).status_code == 403


# Kitchen (subprocess.run is replaced by a recorder; nothing is executed)


def test_printer_is_offline_by_default(lab_printer_off) -> None:
    lab = lab_printer_off
    for route in ("/kitchen/orders/1/receipt", "/kitchen/orders/1/items/2/label"):
        assert lab.client.post(route, headers=lab.as_("farrukh")).status_code == 503
    assert lab.commands.calls == []


def test_receipt_printing_passes_an_argument_list(lab) -> None:
    response = lab.client.post("/kitchen/orders/1/receipt", headers=lab.as_("farrukh"))
    assert response.status_code == 200
    [(args, kwargs)] = lab.commands.calls
    assert args == ["tandir-receipt", "--order", "1", "--customer", "Alice Karimova"]
    assert not kwargs.get("shell")


def test_manager_prints_a_label_for_their_branchs_order(lab) -> None:
    response = lab.client.post("/kitchen/orders/1/items/2/label", headers=lab.as_("farrukh"))
    assert response.status_code == 200
    assert len(lab.commands.calls) == 1


@pytest.mark.parametrize("route", ["/kitchen/orders/2/receipt", "/kitchen/orders/2/items/3/label"])
def test_kitchen_refuses_another_branchs_order(lab, route: str) -> None:
    assert lab.client.post(route, headers=lab.as_("farrukh")).status_code == 404
    assert lab.commands.calls == []


def test_label_item_must_belong_to_the_order(lab) -> None:
    response = lab.client.post("/kitchen/orders/1/items/3/label", headers=lab.as_("farrukh"))
    assert response.status_code == 404
    assert lab.commands.calls == []


# Files


def test_avatar_downloads(lab) -> None:
    response = lab.client.get("/avatars", params={"name": "alice.png"})
    assert response.status_code == 200
    assert response.content.endswith(b"alice")


@pytest.mark.parametrize("name", ["../cake_photos/1/reference.jpg", "missing.png", "."])
def test_avatar_outside_the_folder_or_missing_is_not_found(lab, name: str) -> None:
    assert lab.client.get("/avatars", params={"name": name}).status_code == 404
