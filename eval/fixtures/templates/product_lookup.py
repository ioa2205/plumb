from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/products/by-sku/{sku}")
def product_by_sku(sku: str, db: Session = Depends(get_db)) -> dict[str, object]:
    row = db.execute(
        text("SELECT id, name, price_cents FROM products WHERE sku = :sku"),
        {"sku": sku},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return dict(row._mapping)
