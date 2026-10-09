from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Customer, LoyaltyCard
from app.schemas import LoyaltyCardOut
from app.security import current_customer

router = APIRouter()


@router.get("/loyalty/{card_id}")
def loyalty_balance(
    card_id: int,
    customer: Customer = Depends(current_customer),
    db: Session = Depends(get_db),
) -> LoyaltyCardOut:
    card = db.get(LoyaltyCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    if card.customer_id != customer.id:
        raise HTTPException(status_code=403, detail="Not your card")
    return LoyaltyCardOut(points=card.points, tier=card.tier)
