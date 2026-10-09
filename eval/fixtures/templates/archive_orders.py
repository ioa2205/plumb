from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import require_admin

router = APIRouter()


@router.post("/admin/orders/archive")
def archive_orders(
    before: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    result = db.execute(
        text("UPDATE orders SET archived = 1 WHERE archived = 0 AND created_at < :before"),
        {"before": before},
    )
    db.commit()
    return {"archived": result.rowcount}
