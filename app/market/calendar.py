"""NSE trading calendar: market hours, sessions, holidays (configured + auto-fetched)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
PRE_OPEN_START = dtime(9, 0)
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
POST_CLOSE_END = dtime(16, 0)

_holiday_cache: dict = {"fetched_at": 0.0, "dates": set(), "attempted": False}
_lock = threading.Lock()
HOLIDAY_TTL = 24 * 3600


def now_ist() -> datetime:
    return datetime.now(IST)


def _fetch_nse_holidays() -> set[str]:
    """Official NSE capital-market holiday list via nsemine (best effort)."""
    from nsemine.nse import get_holiday_lists

    df = get_holiday_lists()
    if df is None or df.empty:
        return set()
    return {d.strftime("%Y-%m-%d") for d in df["date"].dropna()}


def holidays(refresh: bool = False) -> set[str]:
    """Configured holidays plus the NSE list (fetched at most once a day, never in offline mode)."""
    settings = get_settings()
    configured = settings.holiday_set
    if settings.offline_mode:
        return configured
    now = time.monotonic()
    with _lock:
        fresh = _holiday_cache["fetched_at"] and now - _holiday_cache["fetched_at"] < HOLIDAY_TTL
        if refresh or not fresh:
            try:
                _holiday_cache["dates"] = _fetch_nse_holidays()
                _holiday_cache["fetched_at"] = now
            except Exception as exc:
                log.debug("NSE holiday fetch failed: %s", exc)
                # retry no sooner than an hour later
                _holiday_cache["fetched_at"] = now - HOLIDAY_TTL + 3600
        return configured | set(_holiday_cache["dates"])


def is_trading_day(d: date, hol: set[str] | None = None) -> bool:
    if d.weekday() >= 5:
        return False
    return d.strftime("%Y-%m-%d") not in (hol if hol is not None else holidays())


def is_market_open(at: datetime | None = None, holidays_override: set[str] | None = None) -> bool:
    at = (at or now_ist()).astimezone(IST)
    if not is_trading_day(at.date(), holidays_override):
        return False
    return MARKET_OPEN <= at.time() <= MARKET_CLOSE


def session(at: datetime | None = None) -> str:
    """pre-open | open | post-close | closed"""
    at = (at or now_ist()).astimezone(IST)
    if not is_trading_day(at.date()):
        return "closed"
    t = at.time()
    if PRE_OPEN_START <= t < MARKET_OPEN:
        return "pre-open"
    if MARKET_OPEN <= t <= MARKET_CLOSE:
        return "open"
    if MARKET_CLOSE < t <= POST_CLOSE_END:
        return "post-close"
    return "closed"


def next_open(at: datetime | None = None) -> datetime:
    at = (at or now_ist()).astimezone(IST)
    hol = holidays()
    candidate = at.date()
    if not (is_trading_day(candidate, hol) and at.time() < MARKET_OPEN):
        candidate += timedelta(days=1)
        while not is_trading_day(candidate, hol):
            candidate += timedelta(days=1)
    return datetime.combine(candidate, MARKET_OPEN, tzinfo=IST)


def market_status(at: datetime | None = None) -> dict:
    at = (at or now_ist()).astimezone(IST)
    sess = session(at)
    open_ = sess == "open"
    if sess == "open":
        label = "Market open"
    elif sess == "pre-open":
        label = "Pre-open session (09:00-09:15) - showing previous close"
    elif sess == "post-close":
        label = "Market closed - showing today's close"
    elif not is_trading_day(at.date()):
        label = "Market closed (weekend / NSE holiday)"
    elif at.time() < PRE_OPEN_START:
        label = "Pre-market - showing previous close"
    else:
        label = "Market closed - showing today's close"
    nxt = next_open(at)
    delta = nxt - at
    hours = int(delta.total_seconds() // 3600)
    mins = int(delta.total_seconds() % 3600 // 60)
    return {
        "open": open_,
        "session": sess,
        "label": label,
        "ist_time": at.strftime("%d %b %Y, %H:%M IST"),
        "next_open": nxt.strftime("%a %d %b, %H:%M IST"),
        "next_open_in": f"{hours}h {mins}m" if not open_ else None,
    }
