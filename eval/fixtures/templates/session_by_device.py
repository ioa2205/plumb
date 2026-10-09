from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import current_user

router = APIRouter()


@router.delete("/me/sessions")
def sign_out_device(
    device: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    result = db.execute(
        text("DELETE FROM sessions WHERE user_id = :user AND device = :device"),
        {"user": user.id, "device": device},
    )
    db.commit()
    return {"signed_out": result.rowcount}
