import asyncio
from datetime import date, datetime, timezone

from app.alerts.scheduler import news_catalyst, poll_spotlight, price_triggered
from app.models import AlertLog, Holding, SpotlightEntry
from app.portfolio.health import holding_health, portfolio_health
from app.services import analyze


def test_price_trigger_directions():
    e = SpotlightEntry(symbol="X.NS", cutoff_price=100.0, cutoff_direction="above", email="a@b.co")
    assert price_triggered(e, 100.0) and price_triggered(e, 120.0) and not price_triggered(e, 99.9)
    e.cutoff_direction = "below"
    assert price_triggered(e, 99.0) and not price_triggered(e, 101.0)
    e.cutoff_price = None
    assert not price_triggered(e, 1.0)


def test_news_catalyst_threshold(db):
    a = analyze("Tata Motors")
    key, rows = news_catalyst(a)
    assert all(abs(r["impact_score"]) > 0.7 for r in rows)
    assert (key is None) == (len(rows) == 0)


def test_poll_spotlight_sends_alerts_and_dedupes_news(db):
    entry = SpotlightEntry(symbol="TATAMOTORS.NS", name="Tata Motors", cutoff_price=1.0,
                           cutoff_direction="above", email="trader@example.com")
    db.add(entry)
    db.commit()
    eid = entry.id
    result = asyncio.run(poll_spotlight(eid, force=True))
    assert result["status"] == "ok" and "price" in result["alerts"]
    logs = db.query(AlertLog).filter_by(spotlight_id=eid).all()
    assert logs and all(not l.delivered and "outbox" in l.detail for l in logs)
    # Second poll: price alert in cooldown, same news key -> no new alerts
    result2 = asyncio.run(poll_spotlight(eid, force=True))
    assert result2["alerts"] == []


def test_holding_and_portfolio_health(db):
    h = Holding(symbol="INFY.NS", name="Infosys", buy_price=10.0, quantity=5, buy_date=date(2025, 1, 1))
    hh = holding_health(h)
    assert hh.invested == 50.0 and hh.market_value == round(hh.ltp * 5, 2)
    assert hh.pnl == round(hh.market_value - 50.0, 2)
    bad = Holding(symbol="", name="", buy_price=1.0, quantity=1, buy_date=date(2025, 1, 1))
    assert holding_health(bad).error is not None
    ph = portfolio_health([h, bad])
    assert ph.invested == 51.0 and ph.market_value == hh.market_value
    assert ph.sentiment_label in {"Bullish Bias", "Bearish Bias", "Neutral"}
