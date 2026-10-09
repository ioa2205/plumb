from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Address, User
from app.schemas import AddressOut
from app.security import current_user

router = APIRouter()


@router.get("/addresses/{address_id}")
def get_address(
    address_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AddressOut:
    address = db.get(Address, address_id)
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found")
    if address.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your address")
    return AddressOut.model_validate(address)
