from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import Branch, MenuItem, Order, User
from tandir.schemas import BranchOut, HoursIn, MenuItemIn, MenuItemOut, OrderOut
from tandir.security import require_role

router = APIRouter(prefix="/branches", tags=["branches"])

manager = require_role("branch_manager")


def _menu_out(item: MenuItem) -> MenuItemOut:
    return MenuItemOut(
        id=item.id,
        branch_id=item.branch_id,
        name=item.name,
        price_cents=item.price_cents,
        available=item.available,
    )


@router.get("/{branch_id}/menu")
def get_menu(branch_id: int, db: Session = Depends(get_db)) -> list[MenuItemOut]:
    items = db.scalars(select(MenuItem).where(MenuItem.branch_id == branch_id))
    return [_menu_out(i) for i in items]


@router.put("/{branch_id}/menu/{item_id}")
def update_menu_item(
    branch_id: int,
    item_id: int,
    body: MenuItemIn,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> MenuItemOut:
    item = db.get(MenuItem, item_id)
    if item is None or item.branch_id != branch_id:
        raise HTTPException(status_code=404, detail="Menu item not found")
    item.name = body.name
    item.price_cents = body.price_cents
    item.available = body.available
    db.commit()
    return _menu_out(item)


@router.put("/{branch_id}/hours")
def update_hours(
    branch_id: int,
    body: HoursIn,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> BranchOut:
    if user.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="Not your branch")
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    branch.opens_at = body.opens_at
    branch.closes_at = body.closes_at
    db.commit()
    return BranchOut(
        id=branch.id,
        name=branch.name,
        city=branch.city,
        opens_at=branch.opens_at,
        closes_at=branch.closes_at,
    )


@router.get("/{branch_id}/orders")
def branch_orders(
    branch_id: int,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> list[OrderOut]:
    if user.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="Not your branch")
    orders = db.scalars(select(Order).where(Order.branch_id == branch_id).order_by(Order.id))
    return [OrderOut.from_order(o) for o in orders]
