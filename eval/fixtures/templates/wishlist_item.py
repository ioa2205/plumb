from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, WishlistItem
from app.security import current_user

router = APIRouter()


@router.delete("/wishlist/{item_id}", status_code=204)
def remove_from_wishlist(
    item_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    item = db.get(WishlistItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not on your wishlist")
    db.delete(item)
    db.commit()
