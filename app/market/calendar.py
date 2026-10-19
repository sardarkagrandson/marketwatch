"""Trading calendars per market: hours, sessions, holidays (configured, static, or fetched)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.markets import DEFAULT_MARKET, MarketProfile, get_market

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")   # kept for existing imports

_holiday_cache: dict[str, dict] = {}
_lock = threading.Lock()
HOLIDAY_TTL = 24 * 3600


def _profile(market) -> MarketProfile:
    return market if isinstance(market, MarketProfile) else get_market(market)


def now_in(market=DEFAULT_MARKET) -> datetime:
    return datetime.now(_profile(market).zone)


def now_ist() -> datetime:
    return now_in("IN")


def _fetch_nse_holidays() -> set[str]:
    from nsemine.nse import get_holiday_lists

    df = get_holiday_lists()
    if df is None or df.empty:
        return set()
    return {d.strftime("%Y-%m-%d") for d in df["date"].dropna()}


def holidays(market=DEFAULT_MARKET, refresh: bool = False) -> set[str]:
    """Configured holidays (MARKET_HOLIDAYS for India, MARKET_HOLIDAYS_ZA for South Africa) plus the
    profile's static list, plus NSE's official list fetched at most once a day (India, online only)."""
    p = _profile(market)
    settings = get_settings()
    configured = settings.holiday_set if p.id == "IN" else settings.holiday_set_za
    static = {d for days in p.static_holidays.values() for d in days}
    if p.id != "IN" or settings.offline_mode:
        return configured | static
    now = time.monotonic()
    with _lock:
        entry = _holiday_cache.setdefault(p.id, {"fetched_at": 0.0, "dates": set()})
        fresh = entry["fetched_at"] and now - entry["fetched_at"] < HOLIDAY_TTL
        if refresh or not fresh:
            try:
                entry["dates"] = _fetch_nse_holidays()
                entry["fetched_at"] = now
            except Exception as exc:
                log.debug("NSE holiday fetch failed: %s", exc)
                entry["fetched_at"] = now - HOLIDAY_TTL + 3600
        return configured | static | set(entry["dates"])


def is_trading_day(d: date, hol: set[str] | None = None, market=DEFAULT_MARKET) -> bool:
    if d.weekday() >= 5:
        return False
    return d.strftime("%Y-%m-%d") not in (hol if hol is not None else holidays(market))


def is_market_open(at: datetime | None = None, holidays_override: set[str] | None = None, market=DEFAULT_MARKET) -> bool:
    p = _profile(market)
    at = (at or now_in(p)).astimezone(p.zone)
    if not is_trading_day(at.date(), holidays_override, p):
        return False
    return p.open <= at.time() <= p.close


def session(at: datetime | None = None, market=DEFAULT_MARKET) -> str:
    """pre-open | open | post-close | closed"""
    p = _profile(market)
    at = (at or now_in(p)).astimezone(p.zone)
    if not is_trading_day(at.date(), None, p):
        return "closed"
    t = at.time()
    if p.pre_open <= t < p.open:
        return "pre-open"
    if p.open <= t <= p.close:
        return "open"
    if p.close < t <= p.post_close:
        return "post-close"
    return "closed"


def next_open(at: datetime | None = None, market=DEFAULT_MARKET) -> datetime:
    p = _profile(market)
    at = (at or now_in(p)).astimezone(p.zone)
    hol = holidays(p)
    candidate = at.date()
    if not (is_trading_day(candidate, hol, p) and at.time() < p.open):
        candidate += timedelta(days=1)
        while not is_trading_day(candidate, hol, p):
            candidate += timedelta(days=1)
    return datetime.combine(candidate, p.open, tzinfo=p.zone)


def market_status(at: datetime | None = None, market=DEFAULT_MARKET) -> dict:
    p = _profile(market)
    at = (at or now_in(p)).astimezone(p.zone)
    sess = session(at, p)
    open_ = sess == "open"
    tzname = at.strftime("%Z") or p.tz
    hours = f"{p.open:%H:%M}-{p.close:%H:%M}"
    if sess == "open":
        label = f"{p.exchange} open"
    elif sess == "pre-open":
        label = f"Pre-open session - showing previous close"
    elif sess == "post-close":
        label = f"{p.exchange} closed - showing today's close"
    elif not is_trading_day(at.date(), None, p):
        label = f"{p.exchange} closed (weekend / holiday)"
    elif at.time() < p.pre_open:
        label = "Pre-market - showing previous close"
    else:
        label = f"{p.exchange} closed - showing today's close"
    nxt = next_open(at, p)
    delta = nxt - at
    h, m = int(delta.total_seconds() // 3600), int(delta.total_seconds() % 3600 // 60)
    return {
        "market": p.id, "exchange": p.exchange, "open": open_, "session": sess, "label": label,
        "ist_time": at.strftime(f"%d %b %Y, %H:%M {tzname}"), "local_time": at.strftime(f"%d %b %Y, %H:%M {tzname}"),
        "hours": hours, "tz": tzname,
        "next_open": nxt.strftime(f"%a %d %b, %H:%M {tzname}"), "next_open_in": f"{h}h {m}m" if not open_ else None,
    }
