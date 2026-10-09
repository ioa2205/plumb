from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Order, RefundRequest, User
from app.schemas import RefundIn, RefundOut
from app.security import current_user

router = APIRouter()


@router.post("/orders/{order_id}/refund-request", status_code=201)
def request_refund(
    order_id: int,
    body: RefundIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RefundOut:
    order = db.get(Order, order_id)
    if order is None or order.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    refund = RefundRequest(order_id=order.id, reason=body.reason, amount_cents=order.total_cents)
    db.add(refund)
    db.commit()
    return RefundOut.from_refund(refund)
