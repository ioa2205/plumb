from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Subscription, User
from app.schemas import SubscriptionOut
from app.security import current_user

router = APIRouter()


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(
    subscription_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None or subscription.subscriber_id != user.id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.cancelled_at = datetime.now(UTC)
    db.commit()
    return SubscriptionOut.from_subscription(subscription)
