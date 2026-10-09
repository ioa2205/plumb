from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import Order, User
from tandir.security import current_user


def load_order_scoped(db: Session, order_id: int, user: User) -> Order:
    order = db.scalars(
        select(Order).where(Order.id == order_id, Order.customer_id == user.id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def ensure_owner(order: Order, user: User) -> None:
    if order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")


def owned_order(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
