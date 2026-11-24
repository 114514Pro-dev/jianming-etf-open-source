"""Read-only handoff of confirmed strategy targets to a broker-side program."""
from datetime import date
from decimal import Decimal, InvalidOperation

from realtime_paper_engine import RULES, dt


def project_live_signal(*, signal, strategy, calendar, now, observed_at, source_status):
    """Publish a target for review, without deriving orders from paper balances."""
    if not signal or signal.get("valid") is not True or signal.get("strategy") != strategy:
        raise ValueError("尚无已确认的策略信号")
    if source_status not in {"ready", "waiting"}:
        raise ValueError("信号来源待核对")
    now = dt(now)
    confirmed_day = date.fromisoformat(signal["confirmed_day"])
    execution_day = date.fromisoformat(signal["execution_day"])
    cutoff = dt(signal["data_cutoff"])
    known = dt(signal["known_at"])
    eligible = dt(signal["eligible_at"])
    signal_id = signal.get("id")
    if not isinstance(signal_id, str) or not signal_id:
        raise ValueError("缺少信号编号")
    if (
        confirmed_day != calendar.expected_confirmed_day(now)
        or execution_day != calendar.next_session(confirmed_day)
        or cutoff.date() != confirmed_day
        or eligible.date() != execution_day
        or now.date() > execution_day
        or not cutoff <= known <= now
        or not cutoff < eligible
        or not 0 <= (now - dt(observed_at)).total_seconds() <= 60
    ):
        raise ValueError("策略信号已过期或时间待核对")
    raw = signal.get("weights")
    if not isinstance(raw, dict) or not raw or set(raw) - RULES.keys():
        raise ValueError("策略目标权重无效")
    try:
        weights = {symbol: Decimal(str(raw.get(symbol, 0))) for symbol in RULES}
    except InvalidOperation:
        raise ValueError("策略目标权重无效") from None
    if any(not value.is_finite() or not 0 <= value <= 1 for value in weights.values()):
        raise ValueError("策略目标权重无效")
    total = sum(weights.values())
    # The strategy uses float arithmetic before serializing decimal weights.
    if total > Decimal("1.000001") or (strategy == "D0I-BOND-WW" and weights["sh518880"] != 0):
        raise ValueError("策略目标权重无效")
    return {
        "schema": "jianming-etf.confirmed-target.v1",
        "strategy": strategy,
        "signal_id": signal_id,
        "confirmed_day": confirmed_day.isoformat(),
        "execution_day": execution_day.isoformat(),
        "data_cutoff": cutoff.isoformat(),
        "known_at": known.isoformat(),
        "eligible_at": eligible.isoformat(),
        "targets": {
            ("SHSE." if symbol.startswith("sh") else "SZSE.") + symbol[2:]: format(weight, "f")
            for symbol, weight in weights.items()
        },
        "cash_weight": format(max(Decimal(0), 1 - total), "f"),
    }
