from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account, Invoice
from app.pdf import render_invoice
from app.security import current_account

router = APIRouter()


@router.get("/invoices/{invoice_id}.pdf")
def download_invoice(
    invoice_id: int,
    account: Account = Depends(current_account),
    db: Session = Depends(get_db),
) -> Response:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.account_id != account.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return Response(render_invoice(invoice), media_type="application/pdf")
