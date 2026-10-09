from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Thread, User
from app.schemas import ThreadOut
from app.security import current_user

router = APIRouter()


@router.get("/threads/{thread_id}")
def read_thread(
    thread_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ThreadOut:
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Thread not found")
    thread.unread = False
    db.commit()
    return ThreadOut.from_thread(thread)
