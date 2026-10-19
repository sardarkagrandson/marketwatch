from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.market.calendar import is_market_open, market_status, session
from app.market.data import _scale
from app.market.tickers import resolve_ticker, suggest
from app.markets import MARKETS, get_market, market_for_symbol

SAST = ZoneInfo("Africa/Johannesburg")


def test_profiles_and_symbol_routing():
    assert set(MARKETS) == {"IN", "ZA"}
    assert market_for_symbol("SOL.JO").id == "ZA" and market_for_symbol("TCS.NS").id == "IN" and market_for_symbol("X.BO").id == "IN"
    assert market_for_symbol("^J200.JO").id == "ZA" and market_for_symbol("").id == "IN"
    za = get_market("za")
    assert za.currency_symbol == "R" and za.price_divisor == 100 and "ipo" not in za.modules and "mf" in get_market("IN").modules


def test_jse_calendar():
    assert is_market_open(datetime(2026, 10, 19, 9, 30, tzinfo=SAST), market="ZA")
    assert not is_market_open(datetime(2026, 10, 19, 17, 1, tzinfo=SAST), market="ZA")
    assert not is_market_open(datetime(2026, 12, 16, 11, 0, tzinfo=SAST), market="ZA")     # Day of Reconciliation
    assert session(datetime(2026, 10, 19, 8, 45, tzinfo=SAST), market="ZA") == "pre-open"
    st = market_status(datetime(2026, 10, 16, 18, 0, tzinfo=SAST), market="ZA")
    assert st["exchange"] == "JSE" and st["hours"] == "09:00-17:00" and "SAST" in st["next_open"] and "Mon" in st["next_open"]
    # Indian hours unaffected, and 10:00 IST is not JSE-open (06:30 SAST)
    assert is_market_open(datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")), market="IN")
    assert not is_market_open(datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")), market="ZA")


def test_resolution_prefers_active_market_but_finds_both():
    assert resolve_ticker("Naspers", allow_search=False, market="ZA").symbol == "NPN.JO"
    assert resolve_ticker("Naspers", allow_search=False, market="IN").symbol == "NPN.JO"      # found in the other market
    assert resolve_ticker("Tata Motors", allow_search=False, market="ZA").symbol == "TATAMOTORS.NS"
    r = resolve_ticker("SOL.JO", allow_search=False, market="IN")
    assert r.exchange == "JSE" and r.market == "ZA" and r.name == "Sasol"
    assert resolve_ticker("ZZZNOPE", allow_search=False, market="ZA").symbol == "ZZZNOPE.JO"
    assert all(s["market"] == "ZA" and s["symbol"].endswith(".JO") for s in suggest("stan", market="ZA"))
    assert suggest("stan", market="ZA")[0]["base_symbol"] == "SBK"


def test_cents_to_rand_scaling():
    df = pd.DataFrame({"Open": [100.0], "High": [110.0], "Low": [90.0], "Close": [105.0], "Volume": [5.0]})
    out = _scale(df, 100.0)
    assert out["Close"].iloc[0] == 1.05 and out["Volume"].iloc[0] == 5.0 and df["Close"].iloc[0] == 105.0
    assert _scale(df, 1.0) is df


def test_market_switch_and_za_pages(client):
    r = client.get("/market/ZA?next=/", follow_redirects=False)
    assert r.status_code == 303 and r.cookies.get("sod-market") == "ZA"
    client.cookies.set("sod-market", "ZA")
    try:
        home = client.get("/").text
        assert "JSE" in home and "All Share" in home and "Naspers" in home and "Dalal Street" not in home
        assert 'href="/ipo"' not in home and 'href="/mf"' not in home          # India-only modules hidden
        assert "FSCA" in home
        page = client.get("/stock/Sasol").text
        assert "Sasol" in page and 'data-currency="R"' in page and "SOL.JO" in page and "₹" not in page.split("<footer")[0]
        assert client.get("/api/suggest?q=cap").json()[0]["symbol"] == "CPI.JO"
        d = client.get("/api/stock/MTN").json()
        assert d["ticker"]["market"] == "ZA" and d["quote"]["currency"] == "ZAR"
        r = client.post("/api/spotlight", json={"query": "FirstRand", "email": "a@b.co"})
        assert r.json()["symbol"] == "FSR.JO"
        client.delete(f"/api/spotlight/{r.json()['id']}")
        assert client.get("/market/XX", follow_redirects=False).status_code == 404
    finally:
        client.cookies.set("sod-market", "IN")
    assert "Dalal" in client.get("/").text and 'href="/ipo"' in client.get("/").text
