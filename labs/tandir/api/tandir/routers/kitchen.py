import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import Order, OrderItem, User
from tandir.security import require_role

router = APIRouter(prefix="/kitchen", tags=["kitchen"])

manager = require_role("branch_manager")


def _printer_on(request: Request) -> None:
    if not request.app.state.settings.printer_enabled:
        raise HTTPException(status_code=503, detail="Kitchen printer is offline")


def _branch_order(db: Session, order_id: int, user: User) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.branch_id != user.branch_id:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{order_id}/items/{item_id}/label")
def print_cake_label(
    order_id: int,
    item_id: int,
    request: Request,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    _printer_on(request)
    order = _branch_order(db, order_id, user)
    item = db.get(OrderItem, item_id)
    if item is None or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Item not found")
    command = f'tandir-label --order {order.id} --text "{item.inscription or item.name}"'
    subprocess.run(command, shell=True, check=True, timeout=10)
    return {"status": "printed"}


@router.post("/orders/{order_id}/receipt")
def print_receipt(
    order_id: int,
    request: Request,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    _printer_on(request)
    order = _branch_order(db, order_id, user)
    customer = order.customer.display_name
    subprocess.run(
        ["tandir-receipt", "--order", str(order.id), "--customer", customer],
        check=True,
        timeout=10,
    )
    return {"status": "printed"}
