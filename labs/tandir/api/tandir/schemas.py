from pydantic import BaseModel, Field

from tandir.models import Order


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    role: str


class OrderItemIn(BaseModel):
    menu_item_id: int
    quantity: int = Field(ge=1, le=20)
    inscription: str | None = Field(default=None, max_length=120)


class OrderIn(BaseModel):
    branch_id: int
    delivery_address: str = Field(max_length=200)
    items: list[OrderItemIn] = Field(min_length=1)


class OrderItemOut(BaseModel):
    name: str
    quantity: int
    unit_price_cents: int
    inscription: str | None


class OrderOut(BaseModel):
    id: int
    status: str
    branch_id: int
    total_cents: int
    created_at: str

    @classmethod
    def from_order(cls, order: Order) -> "OrderOut":
        return cls(
            id=order.id,
            status=order.status,
            branch_id=order.branch_id,
            total_cents=order.total_cents,
            created_at=order.created_at,
        )


class ReceiptOut(BaseModel):
    order_id: int
    customer_name: str
    delivery_address: str
    items: list[OrderItemOut]
    total_cents: int

    @classmethod
    def from_order(cls, order: Order) -> "ReceiptOut":
        return cls(
            order_id=order.id,
            customer_name=order.customer.display_name,
            delivery_address=order.delivery_address,
            items=[
                OrderItemOut(
                    name=i.name,
                    quantity=i.quantity,
                    unit_price_cents=i.unit_price_cents,
                    inscription=i.inscription,
                )
                for i in order.items
            ],
            total_cents=order.total_cents,
        )


class InvoiceOut(ReceiptOut):
    invoice_number: str

    @classmethod
    def from_order(cls, order: Order) -> "InvoiceOut":
        receipt = ReceiptOut.from_order(order)
        return cls(**receipt.model_dump(), invoice_number=f"TND-{order.id:06d}")


class TrackingOut(BaseModel):
    order_id: int
    status: str
    courier_assigned: bool


class MenuItemIn(BaseModel):
    name: str = Field(max_length=80)
    price_cents: int = Field(ge=0, le=10_000_000)
    available: bool = True


class MenuItemOut(BaseModel):
    id: int
    branch_id: int
    name: str
    price_cents: int
    available: bool


class HoursIn(BaseModel):
    opens_at: str = Field(pattern=r"^\d{2}:\d{2}$")
    closes_at: str = Field(pattern=r"^\d{2}:\d{2}$")


class BranchOut(BaseModel):
    id: int
    name: str
    city: str
    opens_at: str
    closes_at: str


class DeliveryOut(BaseModel):
    order_id: int
    status: str
    delivery_address: str
    customer_name: str
