@router.get("/orders/{order_id}/invoice")
def get_invoice(
    order_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> InvoiceOut:
    order = db.get(Order, order_id)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    return InvoiceOut.from_order(order)
