"""Technical indicators computed natively with pandas.

RSI uses Wilder's smoothing (the `ta` library default), EMAs are standard
exponentially weighted means, and ATR uses Wilder's smoothing of true range.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing: SMA seed over the first `period` values, then
    s_t = (s_{t-1} * (period - 1) + x_t) / period. NaN until the seed is complete."""
    arr = values.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    if len(arr) < period:
        return pd.Series(out, index=values.index)
    seed = np.nanmean(arr[:period])
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(arr)):
        x = arr[i] if np.isfinite(arr[i]) else 0.0
        prev = (prev * (period - 1) + x) / period
        out[i] = prev
    return pd.Series(out, index=values.index)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0.0).iloc[1:]
    loss = (-delta.clip(upper=0.0)).iloc[1:]
    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0.0, 100.0)
    out[avg_gain.isna() | avg_loss.isna()] = np.nan
    return out.reindex(close.index)


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, min_periods=span, adjust=False).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    tr = true_range(high, low, close).iloc[1:]  # first bar has no previous close
    return wilder_smooth(tr, period).reindex(close.index)


def annualized_volatility(close: pd.Series, trading_days: int = 252) -> float | None:
    """Annualized volatility from daily log returns."""
    close = close.dropna()
    if len(close) < 20:
        return None
    log_ret = np.log(close / close.shift(1)).dropna()
    daily = float(log_ret.std(ddof=1))
    if not np.isfinite(daily):
        return None
    return daily * float(np.sqrt(trading_days))


@dataclass
class TechnicalSnapshot:
    rsi_14: float | None
    ema_20: float | None
    ema_50: float | None
    ema_200: float | None
    atr_20: float | None
    atr_pct: float | None
    annualized_volatility: float | None
    last_close: float | None
    rsi_state: str  # overbought | oversold | neutral | n/a
    above_ema_200: bool | None
    ema_trend: str  # bullish | bearish | mixed | n/a
    setups: list[str] = field(default_factory=list)
    breakdowns: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rsi_14": _r(self.rsi_14, 2),
            "ema_20": _r(self.ema_20, 2),
            "ema_50": _r(self.ema_50, 2),
            "ema_200": _r(self.ema_200, 2),
            "atr_20": _r(self.atr_20, 2),
            "atr_pct": _r(self.atr_pct, 2),
            "annualized_volatility": _r(self.annualized_volatility, 4),
            "last_close": _r(self.last_close, 2),
            "rsi_state": self.rsi_state,
            "above_ema_200": self.above_ema_200,
            "ema_trend": self.ema_trend,
            "setups": self.setups,
            "breakdowns": self.breakdowns,
        }


def _r(v: float | None, n: int) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), n)


def _last(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    v = series.iloc[-1]
    return None if pd.isna(v) else float(v)


def compute_snapshot(history: pd.DataFrame) -> TechnicalSnapshot:
    """Compute indicators from an OHLCV dataframe (columns: Open High Low Close Volume)."""
    if history is None or history.empty or "Close" not in history:
        return TechnicalSnapshot(None, None, None, None, None, None, None, None, "n/a", None, "n/a")

    df = history.dropna(subset=["Close"]).copy()
    close = df["Close"].astype(float)
    high = df["High"].astype(float) if "High" in df else close
    low = df["Low"].astype(float) if "Low" in df else close

    rsi_v = _last(rsi(close, 14))
    e20, e50, e200 = _last(ema(close, 20)), _last(ema(close, 50)), _last(ema(close, 200))
    atr_v = _last(atr(high, low, close, 20))
    last_close = _last(close)
    vol = annualized_volatility(close)

    rsi_state = "n/a"
    if rsi_v is not None:
        rsi_state = "overbought" if rsi_v >= 70 else "oversold" if rsi_v <= 30 else "neutral"

    above_200 = None if (e200 is None or last_close is None) else last_close > e200
    ema_trend = "n/a"
    if e20 is not None and e50 is not None and e200 is not None:
        if e20 > e50 > e200:
            ema_trend = "bullish"
        elif e20 < e50 < e200:
            ema_trend = "bearish"
        else:
            ema_trend = "mixed"

    setups: list[str] = []
    breakdowns: list[str] = []
    if ema_trend == "bullish":
        setups.append("EMA stack aligned bullish (20 > 50 > 200)")
    if ema_trend == "bearish":
        breakdowns.append("EMA stack aligned bearish (20 < 50 < 200)")
    if above_200 is True:
        setups.append("Price trading above 200 EMA")
    if above_200 is False:
        breakdowns.append("Price below 200 EMA (long-term trend break)")
    if rsi_state == "oversold":
        setups.append(f"RSI oversold ({rsi_v:.1f}) - potential mean reversion")
        breakdowns.append(f"RSI oversold ({rsi_v:.1f}) - selling pressure")
    if rsi_state == "overbought":
        breakdowns.append(f"RSI overbought ({rsi_v:.1f}) - stretched")
    if e20 is not None and e50 is not None and last_close is not None:
        if e20 > e50 and last_close > e20:
            setups.append("Price above rising short-term EMAs (20/50)")
        if e20 < e50 and last_close < e20:
            breakdowns.append("Price below short-term EMAs (20/50)")

    atr_pct = None if (atr_v is None or not last_close) else atr_v / last_close * 100.0

    return TechnicalSnapshot(
        rsi_14=rsi_v,
        ema_20=e20,
        ema_50=e50,
        ema_200=e200,
        atr_20=atr_v,
        atr_pct=atr_pct,
        annualized_volatility=vol,
        last_close=last_close,
        rsi_state=rsi_state,
        above_ema_200=above_200,
        ema_trend=ema_trend,
        setups=setups,
        breakdowns=breakdowns,
    )
