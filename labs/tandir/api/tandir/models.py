from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    city: Mapped[str]
    opens_at: Mapped[str]
    closes_at: Mapped[str]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    role: Mapped[str]
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    phone: Mapped[str]
    password_hash: Mapped[str]
    avatar: Mapped[str | None]


class PhoneChange(Base):
    __tablename__ = "phone_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    phone: Mapped[str]
    changed_at: Mapped[str]


class LoginSession(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str]


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    name: Mapped[str]
    price_cents: Mapped[int]
    available: Mapped[bool] = mapped_column(default=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    courier_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str]
    total_cents: Mapped[int]
    delivery_address: Mapped[str]
    created_at: Mapped[str]

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    customer: Mapped[User] = relationship(foreign_keys=[customer_id])


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    name: Mapped[str]
    quantity: Mapped[int]
    unit_price_cents: Mapped[int]
    inscription: Mapped[str | None]

    order: Mapped[Order] = relationship(back_populates="items")


class CakePhoto(Base):
    __tablename__ = "cake_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    filename: Mapped[str]
    uploaded_at: Mapped[str]
