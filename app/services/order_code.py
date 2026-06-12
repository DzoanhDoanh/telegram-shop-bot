def format_order_code(order_id: int) -> str:
    return f"DH{order_id:06d}"


def get_order_code(order) -> str:
    order_id = getattr(order, "id", None)
    stored = getattr(order, "order_code", None)
    if stored:
        return stored
    if order_id is None:
        return "N/A"
    return format_order_code(int(order_id))
