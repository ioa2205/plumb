from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import require_admin

router = APIRouter()


@router.get("/admin/users/by-email")
def user_by_email(
    email: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    row = db.execute(
        text("SELECT id, display_name, role FROM users WHERE email = :email"),
        {"email": email},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No such user")
    return dict(row._mapping)
