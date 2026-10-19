"""Portfolio health computations."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict

from app.markets import market_for_symbol
from app.models import Holding
from app.services import analyze

log = logging.getLogger(__name__)


@dataclass
class HoldingHealth:
    id: int
    symbol: str
    name: str
    buy_price: float
    quantity: float
    buy_date: str
    ltp: float | None
    invested: float
    market_value: float | None
    pnl: float | None
    pnl_pct: float | None
    day_change: float | None
    day_change_pct: float | None
    sentiment_score: float | None
    momentum_bias: str
    rsi_14: float | None
    rsi_state: str
    above_ema_200: bool | None
    flags: list[dict] = field(default_factory=list)
    is_stale: bool = False
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PortfolioHealth:
    holdings: list[HoldingHealth]
    invested: float
    market_value: float
    net_pnl: float
    net_pnl_pct: float
    day_change: float
    day_change_pct: float
    weighted_sentiment: float
    sentiment_label: str
    flagged_count: int
    market: dict
    mixed_currencies: bool = False

    def as_dict(self) -> dict:
        d = asdict(self)
        d["holdings"] = [h.as_dict() for h in self.holdings]
        return d


def _flags(analysis) -> list[dict]:
    flags: list[dict] = []
    t, s = analysis.technicals, analysis.sentiment
    for row in analysis.matrix:
        if row["impact_score"] <= -0.7:
            flags.append({"level": "critical", "kind": "news", "text": f"Major negative catalyst: {row['headline'][:90]}"})
            break
    if s.score <= -0.3:
        flags.append({"level": "warning", "kind": "news", "text": f"Net bearish news sentiment ({s.score:+.2f})"})
    if t.above_ema_200 is False:
        flags.append({"level": "warning", "kind": "technical", "text": "Price below 200 EMA (long-term trend break)"})
    if t.rsi_state == "overbought":
        flags.append({"level": "info", "kind": "technical", "text": f"RSI overbought ({t.rsi_14:.0f})"})
    if t.rsi_state == "oversold":
        flags.append({"level": "warning", "kind": "technical", "text": f"RSI oversold ({t.rsi_14:.0f})"})
    if t.ema_trend == "bearish":
        flags.append({"level": "info", "kind": "technical", "text": "EMA stack bearish (20 < 50 < 200)"})
    return flags


def holding_health(h: Holding, analysis=None) -> HoldingHealth:
    invested = h.buy_price * h.quantity
    base = dict(id=h.id, symbol=h.symbol, name=h.name, buy_price=h.buy_price, quantity=h.quantity,
                buy_date=h.buy_date.isoformat(), invested=round(invested, 2))
    try:
        a = analysis or analyze(h.symbol)
    except Exception as exc:
        log.warning("portfolio analysis failed for %s: %s", h.symbol, exc)
        return HoldingHealth(**base, ltp=None, market_value=None, pnl=None, pnl_pct=None, day_change=None,
                             day_change_pct=None, sentiment_score=None, momentum_bias="n/a", rsi_14=None,
                             rsi_state="n/a", above_ema_200=None, error=str(exc)[:200])
    q = a.quote
    mv = q.ltp * h.quantity
    base["name"] = h.name or a.ticker.name
    return HoldingHealth(
        **base, ltp=q.ltp, market_value=round(mv, 2), pnl=round(mv - invested, 2),
        pnl_pct=round((mv / invested - 1) * 100, 2) if invested else None,
        day_change=round(q.change * h.quantity, 2), day_change_pct=q.change_pct,
        sentiment_score=a.sentiment.score, momentum_bias=a.sentiment.momentum_bias,
        rsi_14=a.technicals.rsi_14, rsi_state=a.technicals.rsi_state,
        above_ema_200=a.technicals.above_ema_200, flags=_flags(a), is_stale=q.is_stale,
    )


def portfolio_health(holdings: list[Holding]) -> PortfolioHealth:
    from app.market.data import market_status

    rows = [holding_health(h) for h in holdings]
    priced = [r for r in rows if r.market_value is not None]
    invested = sum(r.invested for r in rows)
    mv = sum(r.market_value for r in priced)
    invested_priced = sum(r.invested for r in priced)
    day = sum(r.day_change or 0.0 for r in priced)
    prev_mv = mv - day
    weighted = sum((r.sentiment_score or 0.0) * r.market_value for r in priced) / mv if mv else 0.0
    label = "Bullish Bias" if weighted > 0.15 else "Bearish Bias" if weighted < -0.15 else "Neutral"
    return PortfolioHealth(
        holdings=rows, invested=round(invested, 2), market_value=round(mv, 2),
        net_pnl=round(mv - invested_priced, 2),
        net_pnl_pct=round((mv / invested_priced - 1) * 100, 2) if invested_priced else 0.0,
        day_change=round(day, 2), day_change_pct=round(day / prev_mv * 100, 2) if prev_mv else 0.0,
        weighted_sentiment=round(weighted, 3), sentiment_label=label,
        flagged_count=sum(1 for r in rows if r.flags), market=market_status(),
        mixed_currencies=len({market_for_symbol(h.symbol).currency for h in holdings}) > 1,
    )
