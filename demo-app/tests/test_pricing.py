import pytest

from app.pricing import discount_percent, final_price


def test_no_coupon_small_order_pays_delivery():
    assert final_price(100) == 140


def test_large_order_gets_free_delivery():
    assert final_price(500) == 500


def test_coupon_is_applied_before_delivery_check():
    # 600 with 25% off is 450, which is below 500, so delivery is added.
    assert final_price(600, "FESTIVE25") == 490


def test_coupon_ignores_case_and_spaces():
    assert discount_percent(" welcome10 ") == 10


def test_unknown_coupon_gives_no_discount():
    assert final_price(1000, "FAKE") == 1000


def test_negative_amount_is_rejected():
    with pytest.raises(ValueError):
        final_price(-1)
