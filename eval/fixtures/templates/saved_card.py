from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PaymentCard, User
from app.security import current_user

router = APIRouter()


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(
    card_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    card = db.get(PaymentCard, card_id)
    if card is None or card.holder_id != user.id:
        raise HTTPException(status_code=404, detail="Card not found")
    db.delete(card)
    db.commit()
