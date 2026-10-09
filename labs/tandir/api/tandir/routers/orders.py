import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from tandir.db import get_db
from tandir.models import CakePhoto, MenuItem, Order, OrderItem, User
from tandir.schemas import (
    InvoiceOut,
    OrderIn,
    OrderItemOut,
    OrderOut,
    ReceiptOut,
    TrackingOut,
)
from tandir.security import current_user
from tandir.services.orders import ensure_owner, load_order_scoped, owned_order

router = APIRouter(prefix="/orders", tags=["orders"])

PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@router.get("")
def list_orders(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[OrderOut]:
    orders = db.scalars(select(Order).where(Order.customer_id == user.id).order_by(Order.id))
    return [OrderOut.from_order(o) for o in orders]


@router.post("", status_code=201)
def place_order(
    body: OrderIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OrderOut:
    order = Order(
        customer_id=user.id,
        branch_id=body.branch_id,
        status="placed",
        total_cents=0,
        delivery_address=body.delivery_address,
        created_at=datetime.now(UTC).isoformat(),
    )
    for line in body.items:
        menu_item = db.get(MenuItem, line.menu_item_id)
        if menu_item is None or menu_item.branch_id != body.branch_id or not menu_item.available:
            raise HTTPException(status_code=422, detail="Menu item not available at this branch")
        order.items.append(
            OrderItem(
                menu_item_id=menu_item.id,
                name=menu_item.name,
                quantity=line.quantity,
                unit_price_cents=menu_item.price_cents,
                inscription=line.inscription,
            )
        )
        order.total_cents += menu_item.price_cents * line.quantity
    db.add(order)
    db.commit()
    return OrderOut.from_order(order)


@router.get("/{order_id}")
def get_order(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OrderOut:
    order = db.scalars(
        select(Order).where(Order.id == order_id, Order.customer_id == user.id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderOut.from_order(order)


@router.get("/{order_id}/receipt")
def get_receipt(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ReceiptOut:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return ReceiptOut.from_order(order)


@router.get("/{order_id}/invoice")
def get_invoice(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> InvoiceOut:
    order = load_order_scoped(db, order_id, user)
    return InvoiceOut.from_order(order)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OrderOut:
    order = db.get(Order, order_id)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in ("placed", "baking"):
        raise HTTPException(status_code=409, detail="Order can no longer be cancelled")
    order.status = "cancelled"
    db.commit()
    return OrderOut.from_order(order)


@router.get("/{order_id}/items")
def list_items(order: Order = Depends(owned_order)) -> list[OrderItemOut]:
    return [
        OrderItemOut(
            name=i.name,
            quantity=i.quantity,
            unit_price_cents=i.unit_price_cents,
            inscription=i.inscription,
        )
        for i in order.items
    ]


@router.get("/{order_id}/tracking")
def track_order(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> TrackingOut:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    ensure_owner(order, user)
    return TrackingOut(
        order_id=order.id, status=order.status, courier_assigned=order.courier_id is not None
    )


@router.post("/{order_id}/photos", status_code=201)
async def upload_photo(
    request: Request,
    file: UploadFile,
    order: Order = Depends(owned_order),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    extension = PHOTO_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP image")
    name = f"{secrets.token_hex(8)}{extension}"
    folder = request.app.state.settings.photo_dir / str(order.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(await file.read())
    db.add(CakePhoto(order_id=order.id, filename=name, uploaded_at=datetime.now(UTC).isoformat()))
    db.commit()
    return {"filename": name}


@router.get("/{order_id}/photos")
def download_photo(
    order_id: int,
    name: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    order = load_order_scoped(db, order_id, user)
    path = request.app.state.settings.photo_dir / str(order.id) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(path)
