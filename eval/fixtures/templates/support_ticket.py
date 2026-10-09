from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Ticket, User
from app.schemas import TicketIn, TicketOut
from app.security import current_user

router = APIRouter()


@router.put("/tickets/{ticket_id}")
def update_ticket(
    ticket_id: int,
    body: TicketIn,
    current: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> TicketOut:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or ticket.requester_id != current.id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.subject = body.subject
    ticket.body = body.body
    db.commit()
    return TicketOut.from_ticket(ticket)
