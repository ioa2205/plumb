from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Booking, Guest
from app.schemas import BookingOut
from app.security import current_guest

router = APIRouter()


@router.get("/bookings/{booking_id}")
def booking_detail(
    booking_id: int,
    me: Guest = Depends(current_guest),
    db: Session = Depends(get_db),
) -> BookingOut:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.guest_id != me.id:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingOut.from_booking(booking)
