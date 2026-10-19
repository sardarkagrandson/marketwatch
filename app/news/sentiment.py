"""Sentiment matrix: structured LLM classification with a lexicon fallback."""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone

from app.config import get_settings
from app.db import session_scope
from app.models import NewsAssessmentCache
from app.news.schemas import NewsArticle, NewsAssessment, NewsMatrix, SentimentSummary

log = logging.getLogger(__name__)

HIGH_IMPACT_THRESHOLD = 0.7

SYSTEM_PROMPT = """You are a financial news analyst covering Indian equities (NSE/BSE).
For each headline you are given, classify it for the named company and estimate the
likely price impact. Be conservative: generic market noise is Neutral with impact 0.
Impact scale: +/-0.2 minor, +/-0.5 material, +/-0.8 or beyond only for major catalysts
(large earnings surprises, regulatory bans, big M&A, fraud, management exits).
Categories: Earnings, Regulatory/Legal, Product/Expansion, Macro/Sector, Management, Other.
Return one assessment per article, copying article_id exactly."""

# ---------------------------------------------------------------- heuristic
_BULLISH = {
    "beat": 0.5, "beats": 0.5, "surge": 0.5, "surges": 0.5, "jump": 0.4, "jumps": 0.4, "rally": 0.4,
    "record": 0.4, "profit rises": 0.5, "profit jumps": 0.6, "upgrade": 0.5, "upgrades": 0.5,
    "raise target": 0.4, "raises target": 0.4, "buy": 0.2, "strong": 0.3, "growth": 0.3, "wins": 0.4,
    "order": 0.3, "contract": 0.3, "expansion": 0.3, "launch": 0.2, "launches": 0.2, "approval": 0.4,
    "dividend": 0.2, "buyback": 0.4, "outperform": 0.4, "higher": 0.2, "gains": 0.3, "soars": 0.6,
    "margin beat": 0.5, "capex": 0.2, "new facility": 0.3, "acquires": 0.3, "stake": 0.2,
}
_BEARISH = {
    "miss": -0.5, "misses": -0.5, "fall": -0.4, "falls": -0.4, "drop": -0.4, "drops": -0.4, "plunge": -0.7,
    "plunges": -0.7, "slump": -0.5, "loss": -0.5, "losses": -0.5, "downgrade": -0.5, "downgrades": -0.5,
    "probe": -0.5, "investigation": -0.5, "lawsuit": -0.6, "penalty": -0.5, "fine": -0.4, "ban": -0.7,
    "recall": -0.6, "fraud": -0.9, "default": -0.8, "resigns": -0.5, "steps down": -0.5, "exit": -0.3,
    "weak": -0.3, "cuts": -0.3, "cut": -0.3, "lower": -0.2, "decline": -0.4, "declines": -0.4,
    "sebi": -0.2, "seeks clarification": -0.3, "notice": -0.3, "strike": -0.4, "debt": -0.2,
    "cautious": -0.2, "sell": -0.2, "underperform": -0.4, "warning": -0.4, "crash": -0.8,
}
_CATEGORIES = [
    ("Earnings", r"\b(q[1-4]|quarter|results?|profit|revenue|ebitda|margin|earnings|net income|guidance|brokerage|target)\b"),
    ("Regulatory/Legal", r"\b(sebi|court|lawsuit|regulator|regulatory|probe|penalty|fine|ban|notice|compliance|tribunal|nclt|cci)\b"),
    ("Management", r"\b(ceo|cfo|chairman|director|board|resign|appoint|steps down|md\b|management|promoter)\b"),
    ("Product/Expansion", r"\b(launch|plant|facility|capex|expansion|acquire|acquisition|merger|order|contract|product|partnership|stake|invest)\b"),
    ("Macro/Sector", r"\b(rbi|policy|rate|inflation|sector|industry|nifty|sensex|market|tariff|budget|gdp|crude|rupee|fii)\b"),
]


def heuristic_assess(article: NewsArticle) -> NewsAssessment:
    text = f"{article.headline} {article.summary}".lower()
    score = 0.0
    hits: list[str] = []
    for lexicon in (_BULLISH, _BEARISH):
        for phrase, weight in lexicon.items():
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                score += weight
                hits.append(phrase)
    score = max(-1.0, min(1.0, math.tanh(score)))
    category = "Other"
    for name, pattern in _CATEGORIES:
        if re.search(pattern, text):
            category = name
            break
    sentiment = "Bullish" if score > 0.15 else "Bearish" if score < -0.15 else "Neutral"
    reason = (
        f"Keyword cues: {', '.join(hits[:4])}." if hits else "No strong directional cues in headline."
    )
    return NewsAssessment(
        article_id=article.id, category=category, sentiment=sentiment,
        impact_score=round(score, 2), reasoning=reason,
    )


# ---------------------------------------------------------------- LLM
def llm_assess(articles: list[NewsArticle], company_name: str, symbol: str) -> list[NewsAssessment]:
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)
    listing = "\n".join(
        f"- article_id={a.id} | {a.published_at:%Y-%m-%d} | {a.source or 'unknown'} | {a.headline}"
        + (f" | {a.summary[:200]}" if a.summary else "")
        for a in articles
    )
    user = f"Company: {company_name} ({symbol})\n\nArticles:\n{listing}"
    try:
        response = client.beta.messages.parse(
            model=settings.sentiment_model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_format=NewsMatrix,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as exc:
        raise RuntimeError(f"LLM rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"LLM API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(f"LLM connection error: {exc}") from exc
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError("LLM declined to classify the batch")
    valid_ids = {a.id for a in articles}
    return [a for a in response.parsed_output.assessments if a.article_id in valid_ids]


# ---------------------------------------------------------------- orchestration
def assess_articles(
    articles: list[NewsArticle], company_name: str, symbol: str
) -> tuple[dict[str, NewsAssessment], str]:
    """Return ({article_id: assessment}, method). Uses SQLite cache; never raises."""
    if not articles:
        return {}, "none"
    settings = get_settings()
    results: dict[str, NewsAssessment] = {}
    sources: set[str] = set()

    with session_scope() as s:
        for a in articles:
            row = s.get(NewsAssessmentCache, a.id)
            if row is not None and (row.source == "llm" or not settings.llm_enabled):
                results[a.id] = NewsAssessment.model_validate_json(row.payload)
                sources.add(row.source)

    pending = [a for a in articles if a.id not in results]
    new_rows: list[tuple[NewsAssessment, str]] = []
    if pending and settings.llm_enabled:
        try:
            for asmt in llm_assess(pending, company_name, symbol):
                results[asmt.article_id] = asmt
                new_rows.append((asmt, "llm"))
                sources.add("llm")
        except Exception as exc:
            log.warning("LLM sentiment failed, falling back to heuristic: %s", exc)
    for a in pending:
        if a.id not in results:
            asmt = heuristic_assess(a)
            results[a.id] = asmt
            new_rows.append((asmt, "heuristic"))
            sources.add("heuristic")

    if new_rows:
        with session_scope() as s:
            for asmt, src in new_rows:
                row = s.get(NewsAssessmentCache, asmt.article_id)
                payload = asmt.model_dump_json()
                if row is None:
                    s.add(NewsAssessmentCache(article_id=asmt.article_id, symbol=symbol, payload=payload, source=src))
                else:
                    row.payload, row.source, row.created_at = payload, src, datetime.now(timezone.utc)

    method = "llm" if sources == {"llm"} else "heuristic" if sources == {"heuristic"} else "mixed" if sources else "none"
    return results, method


def summarize(articles: list[NewsArticle], assessments: dict[str, NewsAssessment], method: str) -> SentimentSummary:
    if not articles:
        return SentimentSummary(score=0.0, momentum_bias="Neutral", recent_score=0.0, article_count=0,
                                bullish=0, bearish=0, neutral=0, high_impact=[], method="none", categories={})
    weights, scores, recent = [], [], []
    counts = {"Bullish": 0, "Bearish": 0, "Neutral": 0}
    categories: dict[str, int] = {}
    high: list[str] = []
    for a in articles:
        asmt = assessments.get(a.id)
        if asmt is None:
            continue
        w = math.exp(-a.age_days / 4.0)  # recency half-life ~2.8 days
        weights.append(w)
        scores.append(asmt.impact_score * w)
        if a.age_days <= 3:
            recent.append(asmt.impact_score)
        counts[asmt.sentiment] += 1
        categories[asmt.category] = categories.get(asmt.category, 0) + 1
        if abs(asmt.impact_score) >= HIGH_IMPACT_THRESHOLD:
            high.append(a.id)
    score = sum(scores) / sum(weights) if weights else 0.0
    recent_score = sum(recent) / len(recent) if recent else score
    if score > 0.15 and recent_score >= score * 0.5:
        bias = "Bullish Bias"
    elif score < -0.15 and recent_score <= score * 0.5:
        bias = "Bearish Bias"
    elif score > 0.25:
        bias = "Bullish Bias"
    elif score < -0.25:
        bias = "Bearish Bias"
    else:
        bias = "Neutral"
    return SentimentSummary(
        score=round(score, 3), momentum_bias=bias, recent_score=round(recent_score, 3),
        article_count=len(articles), bullish=counts["Bullish"], bearish=counts["Bearish"],
        neutral=counts["Neutral"], high_impact=high, method=method, categories=categories,
    )
