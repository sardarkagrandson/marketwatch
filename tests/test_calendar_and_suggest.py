from datetime import datetime

from app.market.calendar import IST, is_market_open, market_status, next_open, session
from app.market.tickers import suggest


def test_sessions_and_holidays():
    hol = {"2026-10-20"}
    assert is_market_open(datetime(2026, 10, 19, 10, 0, tzinfo=IST), hol)        # Monday 10:00
    assert not is_market_open(datetime(2026, 10, 19, 9, 14, tzinfo=IST), hol)
    assert not is_market_open(datetime(2026, 10, 19, 15, 31, tzinfo=IST), hol)
    assert not is_market_open(datetime(2026, 10, 17, 11, 0, tzinfo=IST), hol)    # Saturday
    assert not is_market_open(datetime(2026, 10, 20, 11, 0, tzinfo=IST), hol)    # configured holiday
    assert session(datetime(2026, 10, 19, 9, 5, tzinfo=IST)) == "pre-open"
    assert session(datetime(2026, 10, 19, 15, 45, tzinfo=IST)) == "post-close"
    assert session(datetime(2026, 10, 19, 20, 0, tzinfo=IST)) == "closed"


def test_next_open_and_status():
    friday_evening = datetime(2026, 10, 16, 18, 0, tzinfo=IST)
    nxt = next_open(friday_evening)
    assert nxt.weekday() == 0 and nxt.hour == 9 and nxt.minute == 15
    st = market_status(friday_evening)
    assert st["open"] is False and st["session"] == "closed" and "Mon" in st["next_open"] and st["next_open_in"]
    st_open = market_status(datetime(2026, 10, 19, 12, 0, tzinfo=IST))
    assert st_open["open"] and st_open["next_open_in"] is None


def test_suggest_ranking():
    assert suggest("")[:1] == []
    assert suggest("infy")[0]["symbol"] == "INFY.NS"
    tata = [s["base_symbol"] for s in suggest("tata")]
    assert "TATAMOTORS" in tata and all(s["exchange"] == "NSE" for s in suggest("tata"))
    assert suggest("hdfc bank")[0]["base_symbol"] == "HDFCBANK"
    assert suggest("TATAMOTORS.NS")[0]["base_symbol"] == "TATAMOTORS"
    assert len(suggest("a", limit=3)) == 3


def test_suggest_api(client):
    r = client.get("/api/suggest?q=reli")
    assert r.status_code == 200 and r.json()[0]["base_symbol"] == "RELIANCE"
    assert client.get("/api/suggest?q=").json() == []
