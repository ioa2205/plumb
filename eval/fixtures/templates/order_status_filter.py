from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import require_manager

router = APIRouter()


@router.get("/branch/orders")
def orders_by_status(
    status: str,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = db.execute(
        text(
            "SELECT id, status, total_cents FROM orders "
            "WHERE status = :status AND branch_id = :branch"
        ),
        {"status": status, "branch": user.branch_id},
    )
    return [dict(row._mapping) for row in rows]
