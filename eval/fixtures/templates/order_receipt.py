from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Order, User
from app.schemas import ReceiptOut
from app.security import current_user

router = APIRouter()


@router.get("/orders/{order_id}/receipt")
def get_receipt(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ReceiptOut:
    order = db.get(Order, order_id)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    return ReceiptOut.from_order(order)
