from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Review, User
from app.schemas import ReviewIn, ReviewOut
from app.security import current_user

router = APIRouter()


@router.patch("/reviews/{review_id}")
def edit_review(
    review_id: int,
    body: ReviewIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ReviewOut:
    review = db.get(Review, review_id)
    if review is None or review.author_id != user.id:
        raise HTTPException(status_code=404, detail="Review not found")
    review.rating = body.rating
    review.text = body.text
    db.commit()
    return ReviewOut.from_review(review)
