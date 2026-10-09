from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Merchant, Payout
from app.schemas import PayoutOut
from app.security import current_merchant

router = APIRouter()


@router.get("/payouts/{payout_id}")
def payout_detail(
    payout_id: int,
    merchant: Merchant = Depends(current_merchant),
    db: Session = Depends(get_db),
) -> PayoutOut:
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.merchant_id != merchant.id:
        raise HTTPException(status_code=403, detail="Not your payout")
    return PayoutOut(
        id=payout.id,
        amount_cents=payout.amount_cents,
        iban_last4=payout.iban[-4:],
        status=payout.status,
    )
