from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Album, User
from app.schemas import AlbumOut
from app.security import current_user

router = APIRouter()


@router.get("/albums/{album_id}")
def view_album(
    album_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AlbumOut:
    album = db.get(Album, album_id)
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found")
    if album.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Album not found")
    return AlbumOut(
        id=album.id,
        title=album.title,
        photos=[photo.url for photo in album.photos],
    )
