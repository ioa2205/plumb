from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import require_staff

router = APIRouter()


@router.get("/staff/customers")
def search_customers(
    q: str = "",
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = db.execute(
        text("SELECT id, display_name FROM users WHERE display_name LIKE :q ORDER BY id"),
        {"q": f"%{q}%"},
    )
    return [dict(row._mapping) for row in rows]
