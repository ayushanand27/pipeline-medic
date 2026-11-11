"""Price rules for the demo shop."""

COUPONS = {"WELCOME10": 10, "FESTIVE25": 25}
FREE_DELIVERY_ABOVE = 500
DELIVERY_FEE = 40


def discount_percent(coupon: str | None) -> int:
    if not coupon:
        return 0
    return COUPONS.get(coupon.strip().upper(), 0)


def final_price(amount: float, coupon: str | None = None) -> float:
    """Apply the coupon first, then add delivery if the order is small."""
    if amount < 0:
        raise ValueError("amount cannot be negative")
    discounted = amount * (100 - discount_percent(coupon)) / 100
    delivery = 0 if discounted >= FREE_DELIVERY_ABOVE else DELIVERY_FEE
    return round(discounted + delivery, 2)
