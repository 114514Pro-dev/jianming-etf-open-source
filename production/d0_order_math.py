"""Order sizing/pricing policy shared by the D0 paper service and order previews."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


SYMBOLS = ("sz159915", "sh512800", "sh518880", "sh511010")
LOT = 100
MAX_ORDER_QTY = 1_000_000


def target_quantity(equity, weight, price):
    return int(max(Decimal(0), equity * weight) / price / LOT) * LOT


def limit_price(symbol, side, price, previous_close):
    tick = Decimal("0.001")
    band = Decimal("0.20") if symbol == "sz159915" else Decimal("0.10")
    tolerance = Decimal("1.002") if side == "buy" else Decimal("0.998")
    rounding = ROUND_CEILING if side == "buy" else ROUND_FLOOR
    limit = (price * tolerance / tick).to_integral_value(rounding=rounding) * tick
    upper = (previous_close * (1 + band) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    lower = (previous_close * (1 - band) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    return max(lower, min(upper, limit))


def commission(notional, rate, minimum):
    return max(minimum, rate * notional) if notional > 0 else Decimal(0)
