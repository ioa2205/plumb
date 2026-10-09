from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import Order, User
from tandir.schemas import ReceiptOut
from tandir.security import require_role

router = APIRouter(prefix="/admin", tags=["admin"])

staff = require_role("admin", "branch_manager")
admin_only = require_role("admin")

CUSTOMER_SORTS = {"name": "display_name", "joined": "id"}


@router.get("/orders")
def search_orders(
    q: str = "",
    sort: str = "created_at",
    user: User = Depends(staff),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = db.execute(
        text(
            "SELECT orders.id, users.display_name, orders.status, orders.total_cents "
            "FROM orders JOIN users ON users.id = orders.customer_id "
            f"WHERE users.display_name LIKE :q ORDER BY {sort}"
        ),
        {"q": f"%{q}%"},
    )
    return [dict(row._mapping) for row in rows]


@router.get("/customers")
def search_customers(
    name: str = "",
    sort: str = "name",
    user: User = Depends(staff),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    column = CUSTOMER_SORTS.get(sort)
    if column is None:
        raise HTTPException(status_code=400, detail="Unknown sort")
    rows = db.execute(
        text(
            "SELECT id, display_name FROM users "
            f"WHERE role = 'customer' AND display_name LIKE :name ORDER BY {column}"
        ),
        {"name": f"%{name}%"},
    )
    return [dict(row._mapping) for row in rows]


@router.get("/orders/{order_id}")
def admin_get_order(
    order_id: int,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ReceiptOut:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return ReceiptOut.from_order(order)
