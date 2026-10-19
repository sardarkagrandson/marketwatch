"""IPO service: assembles upcoming cards and recently-listed performance with SQLite caching."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from app.config import get_settings
from app.db import session_scope
from app.ipo import sources
from app.ipo.analysis import assess
from app.ipo.schemas import IPOAssessment, IPOCard, IPOListing, ListedIPO
from app.models import IPOCache
from app.news.ingest import dedupe, fetch_query, filter_recent, synthetic_news
from app.news.sentiment import assess_articles, summarize

log = logging.getLogger(__name__)

LIST_TTL = timedelta(hours=1)
ASSESS_TTL = timedelta(hours=12)
NEWS_DAYS = 14
RECENT_DAYS = 60


# ---------------------------------------------------------------- cache helpers
def _cache_get(key: str, ttl: timedelta):
    with session_scope() as s:
        row = s.get(IPOCache, key)
        if row is None:
            return None
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > ttl:
            return None
        return json.loads(row.payload)


def _cache_set(key: str, payload) -> None:
    with session_scope() as s:
        row = s.get(IPOCache, key)
        data = json.dumps(payload, default=str)
        if row is None:
            s.add(IPOCache(key=key, payload=data, fetched_at=datetime.now(timezone.utc)))
        else:
            row.payload, row.fetched_at = data, datetime.now(timezone.utc)


# ---------------------------------------------------------------- upcoming
def upcoming_listings(force: bool = False) -> list[IPOListing]:
    settings = get_settings()
    if settings.offline_mode:
        rows = sources.demo_upcoming()
    else:
        cached = None if force else _cache_get("ipo:upcoming", LIST_TTL)
        if cached is not None:
            rows = [IPOListing.model_validate(r) for r in cached]
        else:
            rows = sources.fetch_nse_upcoming()
            if rows:
                gmp = sources.fetch_gmp_table()
                for r in rows:
                    hit = sources.match_gmp(r, gmp)
                    if hit is not None:
                        r.gmp, r.gmp_source = hit, "grey-market page"
                _cache_set("ipo:upcoming", [r.model_dump(mode="json") for r in rows])
    overrides = sources.load_overrides()
    rows = [sources.apply_overrides(r, overrides) for r in rows]
    today = date.today()
    for r in rows:
        if r.open_date and r.close_date:
            r.status = sources._status(r.open_date, r.close_date, today)
    rows = [r for r in rows if r.close_date is None or r.close_date >= today - timedelta(days=2)]
    order = {"open": 0, "upcoming": 1, "closed": 2}
    return sorted(rows, key=lambda r: (order.get(r.status, 3), r.open_date or date.max))


def _ipo_news(listing: IPOListing) -> tuple[list[dict], float | None]:
    key = f"ipo:news:{listing.key}"
    settings = get_settings()
    if settings.offline_mode:
        arts = synthetic_news(listing.key, listing.company)[:5]
    else:
        cached = _cache_get(key, timedelta(seconds=settings.news_cache_seconds))
        if cached is not None:
            from app.news.schemas import NewsArticle

            arts = [NewsArticle.model_validate(a) for a in cached]
        else:
            arts = filter_recent(dedupe(fetch_query(f'"{listing.company}" IPO', NEWS_DAYS)), NEWS_DAYS)[:5]
            _cache_set(key, [a.model_dump(mode="json") for a in arts])
    if not arts:
        return [], None
    assessments, method = assess_articles(arts, listing.company, listing.key)
    summary = summarize(arts, assessments, method)
    rows = []
    for a in arts:
        asmt = assessments.get(a.id)
        rows.append({
            "headline": a.headline, "source": a.source, "link": a.link,
            "published_label": a.published_at.strftime("%d %b"),
            "sentiment": asmt.sentiment if asmt else "Neutral",
            "impact_score": asmt.impact_score if asmt else 0.0,
        })
    return rows, summary.score


def _assessment_for(listing: IPOListing, headlines: list[str], news_score: float | None) -> tuple[IPOAssessment, str]:
    key = f"ipo:assess:{listing.key}"
    cached = _cache_get(key, ASSESS_TTL)
    if cached and (cached.get("method") == "llm" or not get_settings().llm_enabled):
        return IPOAssessment.model_validate(cached["assessment"]), cached["method"]
    result, method = assess(listing, headlines, news_score)
    _cache_set(key, {"assessment": result.model_dump(), "method": method})
    return result, method


def upcoming_cards(force: bool = False) -> list[IPOCard]:
    cards: list[IPOCard] = []
    for listing in upcoming_listings(force):
        try:
            news, score = _ipo_news(listing)
        except Exception as exc:
            log.warning("IPO news failed for %s: %s", listing.company, exc)
            news, score = [], None
        try:
            assessment, method = _assessment_for(listing, [n["headline"] for n in news], score)
        except Exception as exc:
            log.warning("IPO assessment failed for %s: %s", listing.company, exc)
            assessment, method = None, "none"
        cards.append(IPOCard(listing=listing, assessment=assessment, assessment_method=method, news=news, news_score=score))
    return cards


# ---------------------------------------------------------------- recently listed
def _performance(item: ListedIPO) -> ListedIPO:
    from app.market.data import get_engine

    try:
        engine = get_engine()
        hist = engine.history(item.symbol, "6mo")
        if item.listing_date:
            since = hist[hist.index.date >= item.listing_date] if hasattr(hist.index, "date") else hist
            if not since.empty:
                hist_l = since
            else:
                hist_l = hist.tail(30)
        else:
            hist_l = hist.tail(30)
        first = hist_l.iloc[0]
        quote = engine.quote(item.symbol)
        item.listing_open = round(float(first["Open"]), 2)
        item.listing_close = round(float(first["Close"]), 2)
        item.ltp = quote.ltp
        item.is_stale = quote.is_stale
        if item.issue_price:
            item.listing_gain_pct = round((item.listing_close / item.issue_price - 1) * 100, 2)
            item.total_gain_pct = round((item.ltp / item.issue_price - 1) * 100, 2)
    except Exception as exc:
        item.error = str(exc)[:160]
    return item


def recently_listed(force: bool = False) -> list[ListedIPO]:
    settings = get_settings()
    if settings.offline_mode:
        rows = sources.demo_past()
    else:
        cached = None if force else _cache_get("ipo:past", LIST_TTL)
        if cached is not None:
            rows = [ListedIPO.model_validate(r) for r in cached]
        else:
            rows = sources.fetch_nse_past(RECENT_DAYS)
            _cache_set("ipo:past", [r.model_dump(mode="json") for r in rows])
    overrides = sources.load_overrides()
    for r in rows:
        o = overrides.get(r.key)
        if o:
            if o.get("issue_price") is not None:
                r.issue_price = float(o["issue_price"])
            if o.get("listing_date"):
                r.listing_date = date.fromisoformat(str(o["listing_date"]))
    # Operator-added listings that NSE did not return (e.g. BSE-only)
    for key, o in overrides.items():
        if o.get("listed") and key not in {r.key for r in rows}:
            rows.append(ListedIPO(key=key, symbol=o.get("symbol", f"{key}.NS"), company=o.get("company", key),
                                  issue_price=o.get("issue_price"),
                                  listing_date=date.fromisoformat(o["listing_date"]) if o.get("listing_date") else None))
    rows = [_performance(r) for r in rows]
    if settings.offline_mode:  # make the synthetic series tell a believable story
        for r, factor in zip(rows, (1.18, 0.93, 1.42)):
            if r.listing_open:
                r.issue_price = round(r.listing_open / factor, 2)
                r.listing_gain_pct = round((r.listing_close / r.issue_price - 1) * 100, 2)
                r.total_gain_pct = round((r.ltp / r.issue_price - 1) * 100, 2)
    return sorted(rows, key=lambda r: r.listing_date or date.min, reverse=True)
