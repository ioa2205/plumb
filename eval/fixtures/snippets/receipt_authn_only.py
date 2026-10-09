@router.get("/orders/{order_id}/receipt")
def get_receipt(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ReceiptOut:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return ReceiptOut.from_order(order)
