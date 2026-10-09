from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import Order, User
from tandir.schemas import DeliveryOut
from tandir.security import require_role

router = APIRouter(prefix="/courier", tags=["courier"])

courier = require_role("courier")


def _delivery(order: Order) -> DeliveryOut:
    return DeliveryOut(
        order_id=order.id,
        status=order.status,
        delivery_address=order.delivery_address,
        customer_name=order.customer.display_name,
    )


@router.get("/deliveries")
def my_deliveries(
    user: User = Depends(courier), db: Session = Depends(get_db)
) -> list[DeliveryOut]:
    orders = db.scalars(select(Order).where(Order.courier_id == user.id).order_by(Order.id))
    return [_delivery(o) for o in orders]


@router.get("/orders/{order_id}")
def delivery_detail(
    order_id: int,
    user: User = Depends(courier),
    db: Session = Depends(get_db),
) -> DeliveryOut:
    order = db.get(Order, order_id)
    if order is None or order.courier_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    return _delivery(order)
