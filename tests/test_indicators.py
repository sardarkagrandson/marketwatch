import numpy as np
import pandas as pd

from app.market.indicators import annualized_volatility, atr, compute_snapshot, ema, rsi


def _df(n=300, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1000.0},
                        index=pd.bdate_range("2025-01-01", periods=n))


def test_rsi_bounds_and_extremes():
    df = _df()
    r = rsi(df["Close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    up = pd.Series(np.linspace(100, 200, 40))
    assert rsi(up).iloc[-1] == 100.0
    down = pd.Series(np.linspace(200, 100, 40))
    assert rsi(down).iloc[-1] < 1e-6


def test_rsi_matches_wilder_loop():
    """Vectorised RSI must equal a straightforward Wilder smoothing loop."""
    close = _df(n=120, seed=7)["Close"].reset_index(drop=True)
    period = 14
    deltas = close.diff().fillna(0.0).tolist()
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    expected = {period: 100 - 100 / (1 + avg_gain / avg_loss)}
    for i in range(period + 1, len(close)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        expected[i] = 100 - 100 / (1 + avg_gain / avg_loss)
    out = rsi(close, period)
    assert out.iloc[:period].isna().all()
    for i in range(period, len(close)):
        assert abs(out.iloc[i] - expected[i]) < 1e-9, i


def test_ema_and_atr_shapes():
    df = _df()
    e = ema(df["Close"], 20)
    assert e.isna().sum() == 19 and np.isfinite(e.iloc[-1])
    a = atr(df["High"], df["Low"], df["Close"], 20)
    assert a.dropna().gt(0).all()


def test_snapshot_fields_and_signals():
    snap = compute_snapshot(_df())
    d = snap.as_dict()
    for k in ("rsi_14", "ema_20", "ema_50", "ema_200", "atr_20", "annualized_volatility"):
        assert d[k] is not None
    assert snap.rsi_state in {"overbought", "oversold", "neutral"}
    assert snap.ema_trend in {"bullish", "bearish", "mixed"}
    assert isinstance(snap.setups, list)


def test_snapshot_handles_short_history():
    snap = compute_snapshot(_df(n=10))
    assert snap.ema_200 is None and snap.rsi_state in {"n/a", "neutral", "overbought", "oversold"}
    assert compute_snapshot(pd.DataFrame()).rsi_state == "n/a"


def test_annualized_volatility_scale():
    df = _df(n=1000)
    vol = annualized_volatility(df["Close"])
    assert 0.18 < vol < 0.30  # generated with 1.5% daily sigma ~ 23.8% annual
