from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Notification, User
from app.security import current_user

router = APIRouter()


@router.post("/notifications/{notification_id}/read", status_code=204)
def mark_read(
    notification_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.recipient_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    db.commit()
