"""High-level analysis service combining market data, technicals and news."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.market.data import Quote, get_engine, market_status, sparkline_points
from app.market.indicators import TechnicalSnapshot, compute_snapshot
from app.market.probability import TouchProbability, touch_probability
from app.market.tickers import ResolvedTicker, resolve_ticker
from app.news.ingest import get_news
from app.news.schemas import NewsArticle, NewsAssessment, SentimentSummary
from app.news.sentiment import assess_articles, summarize

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Signals shown are statistical and news-derived biases, not investment advice. "
    "Equity investments are subject to market risk; past performance does not guarantee future results. "
    "Please consult a SEBI-registered advisor before trading."
)


def disclaimer_for(profile) -> str:
    return (
        "Signals shown are statistical and news-derived biases, not investment advice. "
        "Equity investments are subject to market risk; past performance does not guarantee future results. "
        f"Please consult {profile.disclaimer_regulator} before trading."
    )


@dataclass
class StockAnalysis:
    ticker: ResolvedTicker
    quote: Quote
    technicals: TechnicalSnapshot
    news: list[NewsArticle]
    assessments: dict[str, NewsAssessment]
    sentiment: SentimentSummary
    news_fetched_at: datetime
    sparkline: list[float] = field(default_factory=list)
    market: dict = field(default_factory=dict)

    @property
    def matrix(self) -> list[dict]:
        rows = []
        for a in self.news:
            asmt = self.assessments.get(a.id)
            if asmt is None:
                continue
            rows.append({
                "id": a.id,
                "headline": a.headline,
                "source": a.source,
                "published_at": a.published_at.isoformat(),
                "published_label": a.published_at.strftime("%d %b, %H:%M"),
                "link": a.link,
                "category": asmt.category,
                "sentiment": asmt.sentiment,
                "impact_score": asmt.impact_score,
                "reasoning": asmt.reasoning,
                "high_impact": abs(asmt.impact_score) >= 0.7,
            })
        return rows

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker.as_dict(),
            "quote": self.quote.as_dict(),
            "technicals": self.technicals.as_dict(),
            "sentiment": self.sentiment.model_dump(),
            "news_matrix": self.matrix,
            "news_fetched_at": self.news_fetched_at.isoformat(),
            "sparkline": self.sparkline,
            "market": self.market,
            "disclaimer": DISCLAIMER,
        }


def analyze(query: str, include_news: bool = True, market: str = "IN") -> StockAnalysis:
    ticker = resolve_ticker(query, market=market)
    engine = get_engine()
    history = engine.history(ticker.symbol, "1y")
    quote = engine.quote(ticker.symbol)
    if ticker.method in ("fallback", "exact-symbol") and quote.name and quote.name != ticker.symbol:
        ticker.name = quote.name
    technicals = compute_snapshot(history)

    news: list[NewsArticle] = []
    assessments: dict[str, NewsAssessment] = {}
    method = "none"
    fetched_at = datetime.now()
    if include_news:
        try:
            news, fetched_at = get_news(ticker.symbol, ticker.name)
            assessments, method = assess_articles(news, ticker.name, ticker.symbol)
        except Exception as exc:
            log.warning("news pipeline failed for %s: %s", ticker.symbol, exc)
    sentiment = summarize(news, assessments, method)

    return StockAnalysis(
        ticker=ticker, quote=quote, technicals=technicals, news=news, assessments=assessments,
        sentiment=sentiment, news_fetched_at=fetched_at, sparkline=sparkline_points(history),
        market=market_status(market=ticker.market),
    )


def probability_for(query: str, target_price: float, horizon_days: int, market: str = "IN") -> tuple[ResolvedTicker, Quote, TouchProbability]:
    ticker = resolve_ticker(query, market=market)
    engine = get_engine()
    history = engine.history(ticker.symbol, "1y")
    quote = engine.quote(ticker.symbol)
    snap = compute_snapshot(history)
    if snap.annualized_volatility is None:
        raise ValueError("Not enough price history to estimate volatility")
    return ticker, quote, touch_probability(quote.ltp, target_price, snap.annualized_volatility, horizon_days)
