from datetime import date, timedelta

from app.mf import service, sources
from app.mf.taxonomy import KINDS, classify

SAMPLE = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Debt Scheme - Liquid Fund)

Aditya Birla Sun Life Mutual Fund

119568;INF209K01VA3;INF209K01VB1;Aditya Birla Sun Life Liquid Fund - Direct Plan - Growth;412.1234;17-Oct-2026
119569;INF209K01VC9;-;Aditya Birla Sun Life Liquid Fund - Regular Plan - IDCW Daily;100.1950;17-Oct-2026

Open Ended Schemes(Equity Scheme - Small Cap Fund)

Nippon India Mutual Fund

118778;INF204K01K15;-;Nippon India Small Cap Fund - Direct Plan - Growth Plan;182.5541;17-Oct-2026

Open Ended Schemes(Other Scheme - Index Funds)

UTI Mutual Fund

120716;INF789F1AUS7;-;UTI Nifty 50 Index Fund - Direct Plan - Growth Option;160.0031;17-Oct-2026
"""


def test_parse_amfi_and_classify():
    rows = sources.parse_amfi(SAMPLE)
    assert [r.code for r in rows] == ["119568", "119569", "118778", "120716"]
    liq, liq_idcw, small, idx = rows
    assert liq.kind == "liquid" and liq.direct and liq.growth and liq.nav == 412.1234 and liq.nav_date == date(2026, 10, 17)
    assert liq_idcw.direct is False and liq_idcw.growth is False and liq_idcw.amc == "Aditya Birla Sun Life Mutual Fund"
    assert small.kind == "small_cap" and idx.kind == "index"
    assert classify("Open Ended Schemes(Hybrid Scheme - Dynamic Asset Allocation or Balanced Advantage)") == "hybrid_balanced"
    assert classify("Open Ended Schemes(Equity Scheme - ELSS)") == "elss"
    assert classify("Open Ended Schemes(Other Scheme - FoF Overseas)") == "international"
    assert classify("Open Ended Schemes(Other Scheme - FoF Domestic)", "SBI Gold Fund - Direct - Growth") == "gold"
    assert classify("Open Ended Schemes(Other Scheme - FoF Domestic)", "Motilal Oswal Nasdaq 100 FoF - Direct") == "international"
    assert classify("Open Ended Schemes(Other Scheme - Other ETFs)", "Nippon India ETF Gold BeES") == "gold"
    assert classify("Open Ended Schemes(Other Scheme - Index Funds)", "ICICI Pru Nifty Next 50 Index - Direct") == "index"
    assert classify("Open Ended Schemes(Debt Scheme - Gilt Fund)") == "gilt"
    assert classify("Close Ended Schemes(Income)") == "short_debt"
    assert classify("Open Ended Schemes(Equity Scheme - Sectoral/ Thematic)") == "sectoral"


def test_every_kind_has_guide_content():
    for k in KINDS:
        assert k.use_case and k.description and k.horizon and k.risk


def test_returns_computation():
    today = date(2026, 10, 19)
    rows = [(today - timedelta(days=i), 100 * (1.0003 ** (2000 - i))) for i in range(2000, -1, -1)]
    r = service.compute_returns(rows)
    assert r["1m"] is not None and r["1y"] is not None and r["5y"] is not None
    assert abs(r["1y"] - ((1.0003 ** 365) - 1) * 100) < 0.5         # annualised
    assert abs(r["1m"] - ((1.0003 ** 30) - 1) * 100) < 0.2           # simple
    short = service.compute_returns(rows[-100:])
    assert short["1y"] is None and short["3m"] is not None
    assert service.compute_returns([])["1y"] is None


def test_service_offline(db):
    groups = service.groups()
    assert [g["group"] for g in groups] == ["Equity", "Hybrid", "Debt", "Other"]
    large = service.list_schemes("large_cap")
    assert large and all(s.direct and s.growth for s in large)
    assert len(service.list_schemes("large_cap", plan="all", option="all")) > len(large)
    assert service.list_schemes(q="nifty")[0].kind == "index"
    d = service.fund_detail("100008")
    assert d["kind"]["id"] == "small_cap" and d["returns"]["1y"] is not None and d["latest_nav"] > 0
    c = service.chart_series("100008", "6m")
    assert 100 < len(c["points"]) <= 600 and c["intraday"] is False


def test_mf_routes(client):
    html = client.get("/mf").text
    assert 'id="mf-guide"' in html and "Liquid fund" in html and "Short-term parking" in html and "Small-cap fund" in html
    assert "Got it, hide this guide" in html and "mf-guide-seen" in html
    html = client.get("/mf?kind=liquid").text
    assert "Demo Liquid Fund" in html
    page = client.get("/mf/100005").text
    assert "Demo Bluechip Fund" in page and 'data-chart-url="/api/mf/100005/chart"' in page
    assert client.get("/api/mf/kinds").json()[0]["group"] == "Equity"
    assert client.get("/api/mf/schemes?kind=elss").json()[0]["kind"] == "elss"
    assert client.get("/api/mf/100007").json()["returns"]["3y"] is not None
    assert len(client.get("/api/mf/100007/chart?range=all").json()["points"]) > 100
    assert client.get("/mf/999999").status_code == 404


def test_mfapi_list_fallback(monkeypatch):
    import httpx

    class R:
        status_code = 200
        content = b"x"
        def raise_for_status(self): pass
        def json(self):
            return [{"schemeCode": 1, "schemeName": "HDFC Small Cap Fund - Direct Plan - Growth"},
                    {"schemeCode": 2, "schemeName": "SBI Liquid Fund Regular Growth"},
                    {"schemeCode": 3, "schemeName": "Axis Gold ETF"},
                    {"schemeCode": 4, "schemeName": "Kotak Nifty 50 Index Fund - Direct - Growth"}]

    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    rows = sources.fetch_mfapi_list()
    assert [r.kind for r in rows] == ["small_cap", "liquid", "gold", "index"]
    assert rows[0].direct and rows[0].growth and not rows[1].direct
