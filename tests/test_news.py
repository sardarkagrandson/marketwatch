from datetime import datetime, timedelta, timezone

from app.news.ingest import article_id, dedupe, filter_recent, get_news
from app.news.schemas import NewsArticle
from app.news.sentiment import assess_articles, heuristic_assess, summarize


def _a(headline, link, days=0):
    return NewsArticle(id=article_id(headline, link), headline=headline, source="Test",
                       published_at=datetime.now(timezone.utc) - timedelta(days=days), link=link)


def test_dedupe_by_title_and_link():
    arts = [
        _a("Infosys Q2 profit rises 5% - Economic Times", "https://x/1"),
        _a("Infosys Q2 profit rises 5%", "https://x/2"),
        _a("Infosys Q2 profit rises 5%", "https://x/1?utm=1"),
        _a("Infosys announces buyback", "https://x/3"),
    ]
    out = dedupe(arts)
    assert len(out) == 2


def test_filter_recent():
    arts = [_a("old", "https://x/old", days=9), _a("new", "https://x/new", days=1)]
    assert [a.headline for a in filter_recent(arts)] == ["new"]


def test_heuristic_assessment():
    bull = heuristic_assess(_a("Infosys Q2 profit jumps 20%, beats estimates", "https://x/b"))
    bear = heuristic_assess(_a("SEBI probe: company faces penalty over fraud", "https://x/s"))
    assert bull.sentiment == "Bullish" and bull.category == "Earnings" and bull.impact_score > 0.3
    assert bear.sentiment == "Bearish" and bear.category == "Regulatory/Legal" and bear.impact_score < -0.5
    assert -1 <= bull.impact_score <= 1


def test_summary_and_cache(db):
    arts, fetched = get_news("TESTCO.NS", "Test Company")
    assert arts and all(a.age_days <= 7 for a in arts)
    res, method = assess_articles(arts, "Test Company", "TESTCO.NS")
    assert method == "heuristic" and set(res) == {a.id for a in arts}
    s = summarize(arts, res, method)
    assert -1 <= s.score <= 1 and s.article_count == len(arts)
    assert s.momentum_bias in {"Bullish Bias", "Bearish Bias", "Neutral"}
    assert all(abs(res[i].impact_score) >= 0.7 for i in s.high_impact)
    # second call served from cache
    arts2, fetched2 = get_news("TESTCO.NS", "Test Company")
    assert fetched2 == fetched and [a.id for a in arts2] == [a.id for a in arts]
