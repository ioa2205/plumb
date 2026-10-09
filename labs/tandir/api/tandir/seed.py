"""The lab fixture: two branches, six people, menus, orders, photos, and one secret file.

Passwords are lab fixtures, published on purpose so probes can sign in.
"""

from sqlalchemy.orm import Session

from tandir.config import Settings
from tandir.models import Branch, CakePhoto, MenuItem, Order, OrderItem, PhoneChange, User
from tandir.security import hash_password

PASSWORDS = {
    "alice": "alice-lab-pass",
    "bob": "bob-lab-pass",
    "kamol": "kamol-lab-pass",
    "farrukh": "farrukh-lab-pass",
    "nodira": "nodira-lab-pass",
    "admin": "admin-lab-pass",
}

# Distinctive values probes look for to tell whose data came back.
ALICE_ADDRESS = "12 Amir Temur Avenue, flat 7 (ALICE-MARKER)"
BOB_ADDRESS = "4 Navoi Street (BOB-MARKER)"
KITCHEN_SECRET = "PRINTER_TOKEN=tandir-kitchen-SECRET-MARKER"
NOW = "2026-10-01T09:00:00+00:00"


def seed(db: Session, settings: Settings) -> None:
    if db.get(Branch, 1) is not None:
        return
    chilonzor = Branch(id=1, name="Chilonzor", city="Tashkent", opens_at="07:00", closes_at="21:00")
    yunusobod = Branch(id=2, name="Yunusobod", city="Tashkent", opens_at="08:00", closes_at="22:00")
    db.add_all([chilonzor, yunusobod])
    db.flush()

    def person(
        uid: int, username: str, name: str, role: str, branch: int | None, phone: str
    ) -> User:
        return User(
            id=uid,
            username=username,
            display_name=name,
            role=role,
            branch_id=branch,
            phone=phone,
            password_hash=hash_password(
                PASSWORDS[username], salt=username.encode().ljust(16, b"0")
            ),
            avatar=f"{username}.png",
        )

    db.add_all(
        [
            person(1, "alice", "Alice Karimova", "customer", None, "+998 90 111 22 33"),
            person(2, "bob", "Bob Tursunov", "customer", None, "+998 90 444 55 66"),
            person(3, "kamol", "Kamol Courier", "courier", 1, "+998 90 777 88 99"),
            person(4, "farrukh", "Farrukh Manager", "branch_manager", 1, "+998 71 200 00 01"),
            person(5, "nodira", "Nodira Manager", "branch_manager", 2, "+998 71 200 00 02"),
            person(6, "admin", "Tandir Admin", "admin", None, "+998 71 200 00 00"),
        ]
    )
    db.flush()
    db.add_all(
        [
            PhoneChange(
                user_id=1, phone="+998 93 000 11 22", changed_at="2025-03-02T10:00:00+00:00"
            ),
            PhoneChange(
                user_id=1, phone="+998 90 111 22 33", changed_at="2026-01-15T10:00:00+00:00"
            ),
        ]
    )
    db.add_all(
        [
            MenuItem(id=1, branch_id=1, name="Samsa", price_cents=900, available=True),
            MenuItem(id=2, branch_id=1, name="Napoleon cake", price_cents=24000, available=True),
            MenuItem(id=3, branch_id=2, name="Non", price_cents=500, available=True),
            MenuItem(id=4, branch_id=2, name="Medovik cake", price_cents=26000, available=True),
        ]
    )
    db.flush()
    db.add_all(
        [
            Order(
                id=1,
                customer_id=1,
                branch_id=1,
                courier_id=3,
                status="baking",
                total_cents=25800,
                delivery_address=ALICE_ADDRESS,
                created_at=NOW,
                items=[
                    OrderItem(menu_item_id=1, name="Samsa", quantity=2, unit_price_cents=900),
                    OrderItem(
                        menu_item_id=2,
                        name="Napoleon cake",
                        quantity=1,
                        unit_price_cents=24000,
                        inscription="Happy birthday, Dilnoza!",
                    ),
                ],
            ),
            Order(
                id=2,
                customer_id=2,
                branch_id=2,
                courier_id=None,
                status="placed",
                total_cents=26500,
                delivery_address=BOB_ADDRESS,
                created_at=NOW,
                items=[
                    OrderItem(menu_item_id=3, name="Non", quantity=1, unit_price_cents=500),
                    OrderItem(
                        menu_item_id=4,
                        name="Medovik cake",
                        quantity=1,
                        unit_price_cents=26000,
                        inscription="Congratulations, Bob",
                    ),
                ],
            ),
        ]
    )
    db.flush()
    db.add(CakePhoto(order_id=1, filename="reference.jpg", uploaded_at=NOW))
    db.commit()

    photo_dir = settings.photo_dir / "1"
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / "reference.jpg").write_bytes(b"\xff\xd8\xff\xe0 lab placeholder photo")
    settings.avatar_dir.mkdir(parents=True, exist_ok=True)
    for username in PASSWORDS:
        (settings.avatar_dir / f"{username}.png").write_bytes(
            b"\x89PNG lab avatar " + username.encode()
        )
    secrets_dir = settings.data_dir / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "kitchen.env").write_text(KITCHEN_SECRET + "\n", encoding="utf-8")
