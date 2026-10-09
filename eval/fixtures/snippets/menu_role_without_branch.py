@router.put("/branches/{branch_id}/menu/{item_id}")
def update_menu_item(
    branch_id: int,
    item_id: int,
    body: MenuItemIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MenuItemOut:
    if user.role != "branch_manager":
        raise HTTPException(status_code=403, detail="Managers only")
    item = db.get(MenuItem, item_id)
    if item is None or item.branch_id != branch_id:
        raise HTTPException(status_code=404, detail="Item not found")
    item.price = body.price
    db.commit()
    return MenuItemOut.from_item(item)
