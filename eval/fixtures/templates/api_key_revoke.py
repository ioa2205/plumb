from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, User
from app.security import current_user

router = APIRouter()


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(
    key_id: int,
    current: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    if key.user_id != current.id:
        raise HTTPException(status_code=403, detail="Not your key")
    key.revoked_at = datetime.now(UTC)
    db.commit()
