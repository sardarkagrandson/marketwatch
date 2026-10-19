"""Mutual fund service: cached scheme universe, filtering, returns and chart series."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

from app.config import get_settings
from app.db import session_scope
from app.mf import sources
from app.mf.sources import Scheme
from app.mf.taxonomy import GROUP_ORDER, KIND_BY_ID, KINDS

log = logging.getLogger(__name__)

UNIVERSE_TTL = timedelta(hours=12)
HISTORY_TTL = timedelta(hours=6)
_lock = threading.Lock()
_universe: dict = {"schemes": None, "loaded_at": 0.0}


# ---------------------------------------------------------------- generic JSON cache (shares the ipo_cache table)
def _cache_get(key: str, ttl: timedelta):
    from app.models import IPOCache

    with session_scope() as s:
        row = s.get(IPOCache, key)
        if row is None:
            return None
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > ttl:
            return None
        return json.loads(row.payload)


def _cache_set(key: str, payload) -> None:
    from app.models import IPOCache

    with session_scope() as s:
        row = s.get(IPOCache, key)
        data = json.dumps(payload, default=str)
        if row is None:
            s.add(IPOCache(key=key, payload=data, fetched_at=datetime.now(timezone.utc)))
        else:
            row.payload, row.fetched_at = data, datetime.now(timezone.utc)


# ---------------------------------------------------------------- universe
def universe(force: bool = False) -> list[Scheme]:
    """All schemes with today's NAV. In-memory for the process, SQLite for 12h, AMFI beyond that."""
    with _lock:
        if not force and _universe["schemes"] is not None and time.monotonic() - _universe["loaded_at"] < 3600:
            return _universe["schemes"]
    settings = get_settings()
    schemes: list[Scheme] | None = None
    if settings.offline_mode:
        schemes = sources.demo_schemes()
    else:
        cached = None if force else _cache_get("mf:universe:v3", UNIVERSE_TTL)
        if cached is not None:
            schemes = [Scheme.model_validate(r) for r in cached]
        else:
            try:
                schemes = sources.fetch_amfi()
                _cache_set("mf:universe:v3", [s.model_dump(mode="json") for s in schemes])
            except Exception as exc:
                log.warning("AMFI NAV fetch failed: %s", exc)
                stale = _cache_get("mf:universe:v3", timedelta(days=30))
                if stale:
                    schemes = [Scheme.model_validate(r) for r in stale]
                else:
                    try:
                        schemes = sources.fetch_mfapi_list()
                        _cache_set("mf:universe:v3", [s.model_dump(mode="json") for s in schemes])
                    except Exception as exc2:
                        log.warning("mfapi.in scheme list failed too: %s", exc2)
                        schemes = []
    with _lock:
        _universe.update(schemes=schemes, loaded_at=time.monotonic())
    return schemes


def kinds_overview() -> list[dict]:
    """Kinds with scheme counts, grouped for the guide and the browser."""
    counts: dict[str, int] = {}
    for s in universe():
        if s.direct and s.growth:
            counts[s.kind] = counts.get(s.kind, 0) + 1
    out = []
    for k in KINDS:
        d = k.as_dict()
        d["count"] = counts.get(k.id, 0)
        out.append(d)
    return out


def groups() -> list[dict]:
    kinds = kinds_overview()
    return [{"group": g, "kinds": [k for k in kinds if k["group"] == g]} for g in GROUP_ORDER]


def list_schemes(kind: str | None = None, q: str = "", plan: str = "direct", option: str = "growth",
                 limit: int = 200) -> list[Scheme]:
    rows = universe()
    if kind:
        rows = [s for s in rows if s.kind == kind]
    if plan == "direct":
        rows = [s for s in rows if s.direct]
    elif plan == "regular":
        rows = [s for s in rows if not s.direct]
    if option == "growth":
        rows = [s for s in rows if s.growth]
    elif option == "idcw":
        rows = [s for s in rows if not s.growth]
    if q.strip():
        terms = q.lower().split()
        rows = [s for s in rows if all(t in s.name.lower() or t in s.amc.lower() for t in terms)]
    rows.sort(key=lambda s: (s.amc, s.name))
    return rows[:limit]


def get_scheme(code: str) -> Scheme | None:
    return next((s for s in universe() if s.code == code), None)


# ---------------------------------------------------------------- history, returns, chart
def history(code: str) -> tuple[dict, list[tuple[date, float]]]:
    if get_settings().offline_mode:
        return sources.demo_history(code)
    key = f"mf:hist:{code}"
    cached = _cache_get(key, HISTORY_TTL)
    if cached is not None:
        return cached["meta"], [(date.fromisoformat(d), v) for d, v in cached["rows"]]
    meta, rows = sources.fetch_history(code)
    _cache_set(key, {"meta": meta, "rows": [(d.isoformat(), v) for d, v in rows]})
    return meta, rows


PERIODS = [("1m", 30), ("3m", 91), ("6m", 182), ("1y", 365), ("3y", 365 * 3), ("5y", 365 * 5)]


def _nav_on_or_before(rows: list[tuple[date, float]], target: date) -> float | None:
    best = None
    for d, v in rows:
        if d <= target:
            best = v
        else:
            break
    return best


def compute_returns(rows: list[tuple[date, float]]) -> dict:
    """Simple return for periods under a year, CAGR for a year or more; None when history is too short."""
    if len(rows) < 2:
        return {p: None for p, _ in PERIODS} | {"since_inception": None, "inception": None}
    last_d, last_v = rows[-1]
    out: dict = {}
    for label, days in PERIODS:
        start = _nav_on_or_before(rows, last_d - timedelta(days=days))
        if start is None or rows[0][0] > last_d - timedelta(days=days) + timedelta(days=7):
            out[label] = None
            continue
        total = last_v / start - 1
        out[label] = round((( (1 + total) ** (365 / days)) - 1) * 100, 2) if days >= 365 else round(total * 100, 2)
    first_d, first_v = rows[0]
    years = (last_d - first_d).days / 365
    out["since_inception"] = round(((last_v / first_v) ** (1 / years) - 1) * 100, 2) if years >= 1 else round((last_v / first_v - 1) * 100, 2)
    out["inception"] = first_d.isoformat()
    out["annualised"] = {p: d >= 365 for p, d in PERIODS}
    return out


def fund_detail(code: str) -> dict:
    scheme = get_scheme(code)
    meta, rows = history(code)
    if scheme is None and meta:
        scheme = Scheme(code=code, name=meta.get("scheme_name", code), amc=meta.get("fund_house", ""),
                        amfi_category=meta.get("scheme_category", ""), kind="other")
    if scheme is None:
        raise LookupError(f"Scheme {code} not found")
    kind = KIND_BY_ID.get(scheme.kind, KIND_BY_ID["other"])
    returns = compute_returns(rows)
    latest = rows[-1] if rows else (scheme.nav_date, scheme.nav)
    return {
        "scheme": scheme.model_dump(mode="json"), "kind": kind.as_dict(), "returns": returns,
        "latest_nav": latest[1], "latest_date": latest[0].isoformat() if latest[0] else None,
        "points": len(rows),
    }


CHART_RANGES = {"1m": 30, "6m": 182, "1y": 365, "3y": 365 * 3, "5y": 365 * 5, "all": None}


def chart_series(code: str, rng: str = "1y", start: date | None = None, end: date | None = None) -> dict:
    _, rows = history(code)
    if rng == "custom" and start:
        end = end or date.today()
        sel = [(d, v) for d, v in rows if start <= d <= end]
        label = f"{start:%d %b %Y} to {end:%d %b %Y}"
    else:
        days = CHART_RANGES.get(rng, 365)
        sel = rows if days is None else [(d, v) for d, v in rows if d >= rows[-1][0] - timedelta(days=days)] if rows else []
        label = rng
    if len(sel) > 600:
        step = -(-len(sel) // 600)
        sel = sel[::step] + ([sel[-1]] if sel[-1] != sel[::step][-1] else [])
    points = [[int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000), round(v, 4)] for d, v in sel]
    first, last = (points[0][1], points[-1][1]) if points else (None, None)
    return {
        "symbol": code, "range": rng, "interval": "1d", "label": label, "points": points, "first": first, "last": last,
        "change": round(last - first, 4) if points else None,
        "change_pct": round((last / first - 1) * 100, 2) if points and first else None,
        "high": max(p[1] for p in points) if points else None, "low": min(p[1] for p in points) if points else None,
        "intraday": False,
    }
