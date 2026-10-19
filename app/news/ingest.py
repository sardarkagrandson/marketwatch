"""News ingestion from Google News RSS and Yahoo Finance RSS with SQLite caching."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from time import mktime
from urllib.parse import quote_plus

from app.config import get_settings
from app.db import session_scope
from app.models import NewsCache
from app.news.schemas import NewsArticle

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 7
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=IN&lang=en-IN"
USER_AGENT = "Mozilla/5.0 (compatible; SnitchofDalalBot/0.1; +https://example.com)"


def article_id(headline: str, link: str) -> str:
    key = _norm_title(headline) + "|" + (link or "").split("?")[0]
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _norm_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"\s+-\s+[^-]+$", "", t)          # strip trailing " - Source"
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


FEED_TIMEOUT = 12.0


def _parse_feed(url: str) -> list[NewsArticle]:
    import feedparser
    import httpx

    resp = httpx.get(url, timeout=FEED_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    out: list[NewsArticle] = []
    for entry in feed.entries:
        headline = (entry.get("title") or "").strip()
        link = entry.get("link") or ""
        if not headline or not link:
            continue
        ts = entry.get("published_parsed") or entry.get("updated_parsed")
        if ts:
            published = datetime.fromtimestamp(mktime(ts), tz=timezone.utc)
        else:
            published = datetime.now(timezone.utc)
        source = ""
        if isinstance(entry.get("source"), dict):
            source = entry["source"].get("title", "") or ""
        if not source:
            m = re.search(r"\s-\s([^-]+)$", headline)
            source = m.group(1).strip() if m else ""
        summary = re.sub(r"<[^>]+>", "", entry.get("summary", "") or "")[:400]
        out.append(
            NewsArticle(
                id=article_id(headline, link),
                headline=re.sub(r"\s+-\s+[^-]+$", "", headline) if source else headline,
                source=source,
                published_at=published,
                link=link,
                summary=summary,
            )
        )
    return out


def dedupe(articles: list[NewsArticle]) -> list[NewsArticle]:
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out: list[NewsArticle] = []
    for a in sorted(articles, key=lambda x: x.published_at, reverse=True):
        nt = _norm_title(a.headline)
        if a.id in seen_ids or nt in seen_titles:
            continue
        seen_ids.add(a.id)
        seen_titles.add(nt)
        out.append(a)
    return out


def filter_recent(articles: list[NewsArticle], days: int = LOOKBACK_DAYS) -> list[NewsArticle]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [a for a in articles if (a.published_at if a.published_at.tzinfo else a.published_at.replace(tzinfo=timezone.utc)) >= cutoff]


def fetch_query(query: str, days: int = LOOKBACK_DAYS, extra_urls: list[str] | None = None, market: str = "IN") -> list[NewsArticle]:
    """Fetch Google News RSS for an arbitrary query in the market's locale (plus optional extra feeds); never raises."""
    from app.markets import get_market

    loc = get_market(market).news_locale
    urls = [GOOGLE_NEWS_RSS.format(q=quote_plus(f"{query} when:{days}d"), **loc)] + list(extra_urls or [])
    articles: list[NewsArticle] = []
    for url in urls:
        try:
            articles.extend(_parse_feed(url))
        except Exception as exc:  # network failures are non-fatal
            log.warning("news feed failed (%s): %s", url, exc)
    return articles


def fetch_live(symbol: str, company_name: str) -> list[NewsArticle]:
    from app.markets import market_for_symbol

    base = symbol.split(".")[0]
    m = market_for_symbol(symbol)
    articles = fetch_query(f'"{company_name}" OR {base} {"JSE" if m.id == "ZA" else "stock"}', LOOKBACK_DAYS,
                           extra_urls=[YAHOO_RSS.format(symbol=quote_plus(symbol))], market=m.id)
    return filter_recent(dedupe(articles))


def synthetic_news(symbol: str, company_name: str) -> list[NewsArticle]:
    """Deterministic sample headlines used in offline mode."""
    now = datetime.now(timezone.utc)
    templates = [
        ("{c} Q2 net profit rises 18% on strong domestic demand", "Economic Times", 0.4),
        ("SEBI seeks clarification from {c} on related-party disclosures", "Moneycontrol", 1.2),
        ("{c} announces new manufacturing facility, capex of Rs 2,000 crore", "Business Standard", 2.1),
        ("RBI policy stance keeps sector sentiment cautious; {c} shares flat", "Mint", 3.4),
        ("{c} CFO steps down; company names interim replacement", "CNBC-TV18", 4.0),
        ("Brokerages raise target on {c} after margin beat", "Economic Times", 5.2),
        ("{c} faces class action lawsuit over product recall", "Reuters", 6.1),
    ]
    out = []
    for i, (tpl, src, age) in enumerate(templates):
        headline = tpl.format(c=company_name)
        link = f"https://example.com/news/{symbol.lower()}/{i}"
        out.append(NewsArticle(id=article_id(headline, link), headline=headline, source=src,
                               published_at=now - timedelta(days=age), link=link))
    return out


def get_news(symbol: str, company_name: str, force_refresh: bool = False) -> tuple[list[NewsArticle], datetime]:
    """Return (articles, fetched_at); served from SQLite cache when fresh."""
    settings = get_settings()
    ttl = timedelta(seconds=settings.news_cache_seconds)
    now = datetime.now(timezone.utc)

    if not force_refresh:
        with session_scope() as s:
            row = s.get(NewsCache, symbol)
            if row is not None:
                fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
                if now - fetched < ttl:
                    arts = [NewsArticle.model_validate(a) for a in json.loads(row.payload)]
                    return filter_recent(arts), fetched

    articles = synthetic_news(symbol, company_name) if settings.offline_mode else fetch_live(symbol, company_name)

    with session_scope() as s:
        row = s.get(NewsCache, symbol)
        if articles or row is None:
            payload = json.dumps([a.model_dump(mode="json") for a in articles])
            if row is None:
                s.add(NewsCache(symbol=symbol, fetched_at=now, payload=payload))
            else:
                row.fetched_at, row.payload = now, payload
        elif row is not None:
            # Keep stale cache if the live fetch returned nothing (throttled / offline)
            cached = [NewsArticle.model_validate(a) for a in json.loads(row.payload)]
            return filter_recent(cached), (row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc))
    return articles, now
