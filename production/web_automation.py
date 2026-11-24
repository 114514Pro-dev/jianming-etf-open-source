"""Scheduling policy for mainland-listed ETFs, using the bundled verified calendar."""
from datetime import timezone, timedelta

CN = timezone(timedelta(hours=8))


def market_schedule(moment, sessions, verified_through):
    moment = moment.astimezone(CN)
    day = moment.date().isoformat()
    minute = moment.hour * 60 + moment.minute
    valid = day <= verified_through
    session = "休市"
    quotes = history = 1800
    if not valid:
        session = "交易日历需更新"
    elif day in sessions:
        if 9 * 60 + 15 <= minute < 11 * 60 + 31 or 13 * 60 <= minute < 15 * 60 + 1:
            session, quotes, history = "交易中", 30, 300
        elif 11 * 60 + 31 <= minute < 13 * 60:
            session, quotes, history = "午间休市", 1800, 300
        elif 15 * 60 + 1 <= minute < 16 * 60 + 31:
            session, quotes, history = "收盘核对", 1800, 300
    return dict(market_session=session, quote_interval_seconds=quotes,
                history_interval_seconds=history, calendar_valid=valid)
