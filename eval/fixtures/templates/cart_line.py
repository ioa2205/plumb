from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CartLine, User
from app.schemas import CartOut
from app.security import current_user
from app.services.cart import cart_summary

router = APIRouter()


@router.delete("/cart/lines/{line_id}")
def remove_cart_line(
    line_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CartOut:
    line = db.get(CartLine, line_id)
    if line is None or line.cart_owner_id != user.id:
        raise HTTPException(status_code=404, detail="Cart line not found")
    db.delete(line)
    db.commit()
    return cart_summary(db, user)
