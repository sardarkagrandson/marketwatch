def test_pages_render(client):
    for path in ("/", "/stock/Tata%20Motors", "/stock/INFY.NS?target=99999&horizon=20", "/spotlight", "/portfolio"):
        r = client.get(path)
        assert r.status_code == 200, path
    assert "Tata Motors" in client.get("/stock/Tata%20Motors").text
    assert client.get("/stock?q=").status_code == 200  # redirects home


def test_stock_api_shape(client):
    d = client.get("/api/stock/Reliance").json()
    assert d["ticker"]["symbol"] == "RELIANCE.NS"
    assert {"ltp", "previous_close", "day_high", "day_low", "week52_high", "week52_low", "volume", "is_stale"} <= set(d["quote"])
    assert {"rsi_14", "ema_20", "ema_50", "ema_200", "atr_20"} <= set(d["technicals"])
    assert d["sentiment"]["momentum_bias"] in {"Bullish Bias", "Bearish Bias", "Neutral"}
    assert all({"category", "sentiment", "impact_score", "reasoning"} <= set(r) for r in d["news_matrix"])
    assert "not investment advice" in d["disclaimer"]


def test_probability_api(client):
    r = client.post("/api/probability", json={"query": "TCS", "target_price": 10, "horizon_days": 20})
    assert r.status_code == 200
    p = r.json()["probability"]
    assert 0 <= p["touch_probability_pct"] <= 100 and len(p["assumptions"]) >= 3
    assert client.post("/api/probability", json={"query": "TCS", "target_price": -1, "horizon_days": 20}).status_code == 422


def test_spotlight_crud(client):
    r = client.post("/api/spotlight", json={"query": "Wipro", "poll_interval_minutes": 30, "cutoff_price": 500,
                                            "cutoff_direction": "below", "email": "me@example.com"})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert r.json()["symbol"] == "WIPRO.NS"
    r = client.patch(f"/api/spotlight/{eid}", json={"enabled": False, "poll_interval_minutes": 15})
    assert r.json()["enabled"] is False and r.json()["poll_interval_minutes"] == 15
    assert client.post(f"/api/spotlight/{eid}/poll").json()["status"] == "disabled"
    assert any(e["id"] == eid for e in client.get("/api/spotlight").json())
    assert client.delete(f"/api/spotlight/{eid}").status_code == 204
    assert client.delete(f"/api/spotlight/{eid}").status_code == 404
    assert client.post("/api/spotlight", json={"query": "Wipro", "email": "not-an-email"}).status_code == 422


def test_portfolio_crud(client):
    r = client.post("/api/portfolio", json={"query": "HDFC Bank", "buy_price": 1500, "quantity": 4, "buy_date": "2025-02-01"})
    assert r.status_code == 201 and r.json()["symbol"] == "HDFCBANK.NS"
    hid = r.json()["id"]
    d = client.get("/api/portfolio").json()
    assert d["invested"] >= 6000 and any(h["id"] == hid for h in d["holdings"])
    assert client.delete(f"/api/portfolio/{hid}").status_code == 204
    assert client.post("/api/portfolio", json={"query": "HDFC Bank", "buy_price": 1, "quantity": 1, "buy_date": "2999-01-01"}).status_code == 422


def test_form_flows(client):
    r = client.post("/spotlight/add", data={"query": "ITC", "poll_interval_minutes": "60", "cutoff_price": "",
                                            "cutoff_direction": "above", "email": "x@y.co"}, follow_redirects=False)
    assert r.status_code == 303 and "Added" in r.headers["location"]
    r = client.post("/portfolio/add", data={"query": "ITC", "buy_price": "400", "quantity": "10", "buy_date": "2025-01-01"}, follow_redirects=False)
    assert r.status_code == 303 and "added" in r.headers["location"]
