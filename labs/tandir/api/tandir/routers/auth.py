from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import LoginSession, User
from tandir.schemas import LoginIn, LoginOut
from tandir.security import current_user, open_session, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    user = db.scalars(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return LoginOut(token=open_session(db, user), role=user.role)


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.commit()


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "branch_id": user.branch_id,
    }
