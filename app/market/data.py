"""Market data engine: quotes, history, market-hours awareness and caching.

Two providers are available:
  * YFinanceProvider  - live data via yfinance (.NS / .BO tickers)
  * OfflineProvider   - deterministic synthetic data (demo / tests / no network)
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime

import numpy as np
import pandas as pd

from app.config import get_settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- market hours
from app.market.calendar import IST, is_market_open, market_status, now_ist  # noqa: E402,F401


# ---------------------------------------------------------------- cache
class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float):
        with self._lock:
            hit = self._data.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
        return None

    def set(self, key: str, value: object) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_cache = TTLCache()


# ---------------------------------------------------------------- quote model
@dataclass
class Quote:
    symbol: str
    name: str
    currency: str
    ltp: float
    previous_close: float
    day_high: float | None
    day_low: float | None
    week52_high: float | None
    week52_low: float | None
    volume: float | None
    open: float | None
    change: float
    change_pct: float
    as_of: str                 # ISO timestamp of last price
    is_stale: bool             # True when the price is a previous-session close
    market_open: bool
    source: str                # yfinance | offline

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- providers
class YFinanceProvider:
    name = "yfinance"

    def history(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        import yfinance as yf

        df = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
        if df is None or df.empty:
            raise LookupError(f"No price history returned for {symbol}")
        df = df.rename(columns=str.title)
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])

    def quote(self, symbol: str, history: pd.DataFrame) -> Quote:
        import yfinance as yf

        t = yf.Ticker(symbol)
        info: dict = {}
        try:
            fi = t.fast_info
            info = {
                "last_price": fi.last_price,
                "previous_close": fi.previous_close,
                "day_high": fi.day_high,
                "day_low": fi.day_low,
                "year_high": fi.year_high,
                "year_low": fi.year_low,
                "last_volume": fi.last_volume,
                "open": fi.open,
                "currency": fi.currency,
            }
        except Exception as exc:  # fast_info can fail for illiquid tickers
            log.debug("fast_info failed for %s: %s", symbol, exc)
        from app.market.tickers import resolve_ticker

        resolved = resolve_ticker(symbol, allow_search=False)
        name = resolved.name
        if resolved.method == "fallback":  # unknown symbol: ask Yahoo for the long name (slower)
            try:
                name = t.info.get("longName") or t.info.get("shortName") or symbol
            except Exception:
                pass
        return build_quote(symbol, name, history, info, source=self.name)


class NSELiveProvider(YFinanceProvider):
    """Official NSE quote (via nsemine) layered on Yahoo history; falls back to Yahoo."""

    name = "nse"

    def quote(self, symbol: str, history: pd.DataFrame) -> Quote:
        base = symbol.rsplit(".", 1)[0]
        if not symbol.upper().endswith(".NS"):
            return super().quote(symbol, history)
        info = None
        try:
            from nsemine.live import get_stock_live_quotes

            raw = get_stock_live_quotes(base)
            if raw and raw.get("close"):
                ts = raw.get("datetime")
                info = {
                    "last_price": raw.get("close"),
                    "previous_close": raw.get("previous_close"),
                    "day_high": raw.get("high"),
                    "day_low": raw.get("low"),
                    "year_high": raw.get("year_high"),
                    "year_low": raw.get("year_low"),
                    "last_volume": raw.get("volume"),
                    "open": raw.get("open"),
                    "currency": "INR",
                    "last_update": ts.replace(tzinfo=IST).isoformat() if isinstance(ts, datetime) else None,
                    "name": raw.get("name"),
                }
        except Exception as exc:  # blocked IP, NSE outage, library change
            log.debug("NSE live quote failed for %s: %s", symbol, exc)
        if info is None:
            return super().quote(symbol, history)
        from app.market.tickers import resolve_ticker

        resolved = resolve_ticker(symbol, allow_search=False)
        name = resolved.name if resolved.method != "fallback" else (info.get("name") or symbol)
        return build_quote(symbol, name, history, info, source=self.name)


class OfflineProvider:
    """Deterministic synthetic GBM price paths seeded from the symbol."""

    name = "offline"

    def _seed(self, symbol: str) -> int:
        return int(hashlib.sha1(symbol.encode()).hexdigest()[:8], 16)

    def history(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        days = {"1mo": 22, "3mo": 66, "6mo": 126, "1y": 252, "2y": 504}.get(period, 252)
        rng = np.random.default_rng(self._seed(symbol))
        base = 100 + (self._seed(symbol) % 3000)
        drift, vol = 0.08 / 252, (0.18 + (self._seed(symbol) % 20) / 100) / np.sqrt(252)
        rets = rng.normal(drift, vol, days)
        close = base * np.exp(np.cumsum(rets))
        open_ = close * (1 + rng.normal(0, vol / 2, days))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, days)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, days)))
        volume = rng.integers(500_000, 5_000_000, days).astype(float)
        idx = pd.bdate_range(end=now_ist().date(), periods=days)
        return pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx
        )

    def quote(self, symbol: str, history: pd.DataFrame) -> Quote:
        from app.market.tickers import resolve_ticker

        name = resolve_ticker(symbol, allow_search=False).name
        return build_quote(symbol, name, history, {}, source=self.name)


def build_quote(symbol: str, name: str, history: pd.DataFrame, info: dict, source: str) -> Quote:
    last = history.iloc[-1]
    prev = history.iloc[-2] if len(history) > 1 else last
    open_now = is_market_open()

    ltp = _f(info.get("last_price")) or float(last["Close"])
    prev_close = _f(info.get("previous_close")) or float(prev["Close"])
    last_ts = history.index[-1]
    if isinstance(last_ts, pd.Timestamp):
        last_ts = last_ts.tz_localize(IST) if last_ts.tzinfo is None else last_ts.astimezone(IST)
        as_of = last_ts.isoformat()
        last_date = last_ts.date()
    else:
        as_of, last_date = str(last_ts), None
    today = now_ist().date()
    if info.get("last_update"):
        as_of = info["last_update"]
    stale = (not open_now) or (last_date is not None and last_date < today and info.get("last_price") is None)

    change = ltp - prev_close
    change_pct = (change / prev_close * 100.0) if prev_close else 0.0
    year = history.tail(252)
    return Quote(
        symbol=symbol,
        name=name,
        currency=str(info.get("currency") or "INR"),
        ltp=round(ltp, 2),
        previous_close=round(prev_close, 2),
        day_high=_f(info.get("day_high")) or round(float(last["High"]), 2),
        day_low=_f(info.get("day_low")) or round(float(last["Low"]), 2),
        week52_high=_f(info.get("year_high")) or round(float(year["High"].max()), 2),
        week52_low=_f(info.get("year_low")) or round(float(year["Low"].min()), 2),
        volume=_f(info.get("last_volume")) or float(last["Volume"]),
        open=_f(info.get("open")) or round(float(last["Open"]), 2),
        change=round(change, 2),
        change_pct=round(change_pct, 2),
        as_of=as_of,
        is_stale=bool(stale),
        market_open=open_now,
        source=source,
    )


def _f(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if np.isfinite(f) and f != 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- engine
class MarketDataEngine:
    def __init__(self, provider=None) -> None:
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            settings = get_settings()
            if settings.offline_mode:
                self._provider = OfflineProvider()
            elif settings.quote_source.lower() == "yfinance":
                self._provider = YFinanceProvider()
            else:
                self._provider = NSELiveProvider()
        return self._provider

    def history(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        key = f"hist:{self.provider.name}:{symbol}:{period}"
        cached = _cache.get(key, get_settings().history_cache_seconds)
        if cached is not None:
            return cached
        df = self.provider.history(symbol, period)
        _cache.set(key, df)
        return df

    def quote(self, symbol: str) -> Quote:
        key = f"quote:{self.provider.name}:{symbol}"
        ttl = get_settings().quote_cache_seconds if is_market_open() else get_settings().history_cache_seconds
        cached = _cache.get(key, ttl)
        if cached is not None:
            return cached
        q = self.provider.quote(symbol, self.history(symbol))
        _cache.set(key, q)
        return q

    def clear_cache(self) -> None:
        _cache.clear()


_engine: MarketDataEngine | None = None


def get_engine() -> MarketDataEngine:
    global _engine
    if _engine is None:
        _engine = MarketDataEngine()
    return _engine


def set_engine(engine: MarketDataEngine | None) -> None:
    global _engine
    _engine = engine
    _cache.clear()


def sparkline_points(history: pd.DataFrame, n: int = 60) -> list[float]:
    return [round(float(v), 2) for v in history["Close"].tail(n).tolist()]


# ---------------------------------------------------------------- market overview (home page)
INDICES = [
    ("^NSEI", "NIFTY 50"),
    ("^BSESN", "SENSEX"),
    ("^NSEBANK", "NIFTY Bank"),
    ("^CNXIT", "NIFTY IT"),
]
POPULAR = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "TATAMOTORS.NS", "SBIN.NS", "BHARTIARTL.NS"]


def _quote_or_none(symbol: str, name: str | None = None) -> Quote | None:
    try:
        engine = get_engine()
        hist = engine.history(symbol, "6mo")
        key = f"quote:{engine.provider.name}:{symbol}"
        ttl = get_settings().quote_cache_seconds if is_market_open() else get_settings().history_cache_seconds
        q = _cache.get(key, ttl)
        if q is None:
            if isinstance(engine.provider, OfflineProvider):
                from app.market.tickers import resolve_ticker

                q = build_quote(symbol, name or resolve_ticker(symbol, allow_search=False).name, hist, {}, source="offline")
            else:
                q = engine.provider.quote(symbol, hist)
                if name:
                    q.name = name
            _cache.set(key, q)
        q.sparkline = sparkline_points(hist, 30)  # type: ignore[attr-defined]
        return q
    except Exception as exc:
        log.debug("overview quote failed for %s: %s", symbol, exc)
        return None


def market_overview(timeout: float = 8.0) -> dict:
    """Index strip + popular stock cards for the home page; fetched concurrently, best effort."""
    from concurrent.futures import ThreadPoolExecutor, wait

    with ThreadPoolExecutor(max_workers=8) as pool:
        idx_f = {pool.submit(_quote_or_none, sym, name): (sym, name) for sym, name in INDICES}
        pop_f = {pool.submit(_quote_or_none, sym): sym for sym in POPULAR}
        wait(list(idx_f) + list(pop_f), timeout=timeout)
    indices = [f.result() for f in idx_f if f.done() and f.result() is not None]
    popular = [f.result() for f in pop_f if f.done() and f.result() is not None]
    return {"indices": indices, "popular": popular}
