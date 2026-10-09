from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/coupons/{code}")
def coupon_discount(code: str, db: Session = Depends(get_db)) -> dict[str, int]:
    discount = db.execute(
        text(
            "SELECT discount_percent FROM coupons "
            "WHERE code = :code AND expires_at > CURRENT_TIMESTAMP"
        ),
        {"code": code},
    ).scalar()
    if discount is None:
        raise HTTPException(status_code=404, detail="Coupon not valid")
    return {"discount_percent": discount}
