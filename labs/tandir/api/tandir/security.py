import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import LoginSession, User

SESSION_COOKIE = "tandir_session"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, salt_hex, digest_hex = stored.split("$")
    candidate = hash_password(password, bytes.fromhex(salt_hex)).split("$")[2]
    return hmac.compare_digest(candidate, digest_hex)


def open_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token=token, user_id=user.id, created_at=datetime.now(UTC).isoformat()))
    db.commit()
    return token


def _token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token(request)
    login = db.get(LoginSession, token) if token else None
    if login is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    user = db.get(User, login.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Not allowed")
        return user

    return check
