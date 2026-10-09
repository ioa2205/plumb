from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Document, User
from app.security import current_user
from app.storage import open_blob

router = APIRouter()


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    return StreamingResponse(open_blob(document.blob_key), media_type=document.content_type)
