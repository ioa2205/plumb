from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import require_admin

router = APIRouter()


@router.get("/admin/audit")
def audit_entries(
    actor: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = db.execute(
        text(
            "SELECT id, actor, action, created_at FROM audit_log "
            "WHERE actor = :actor ORDER BY created_at DESC LIMIT 100"
        ),
        {"actor": actor},
    )
    return [dict(row._mapping) for row in rows]
