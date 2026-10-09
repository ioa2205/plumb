from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account
from app.security import current_account

router = APIRouter()


@router.get("/invoices/search")
def find_invoice(
    number: str,
    account: Account = Depends(current_account),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    row = db.execute(
        text(
            "SELECT id, number, total_cents FROM invoices "
            "WHERE account_id = :account AND number = :number"
        ),
        {"account": account.id, "number": number},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return dict(row._mapping)
