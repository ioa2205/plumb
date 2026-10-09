from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/catalog")
def list_category(category: str, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.execute(
        text(
            "SELECT id, name, price_cents FROM products "
            "WHERE category = :category AND active = 1"
        ),
        {"category": category},
    ).all()
    return [dict(row._mapping) for row in rows]
