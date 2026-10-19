from datetime import date, timedelta

from app.alerts.scheduler import price_triggered
from app.ipo import sources
from app.ipo.analysis import heuristic_assess
from app.ipo.schemas import IPOFundamentals, IPOListing
from app.ipo.service import recently_listed, upcoming_cards
from app.models import SpotlightEntry


def test_parse_nse_issue_row():
    today = date(2026, 10, 19)
    row = {"symbol": "abcd", "companyName": "ABCD Industries Limited", "series": "EQ",
           "issueStartDate": "18-Oct-2026", "issueEndDate": "21-Oct-2026", "issuePrice": "100 to 105",
           "issueSize": "12,500,000,000", "noOfTimes": "2.35", "status": "Active"}
    l = sources.parse_nse_issue(row, today)
    assert l.key == "ABCD" and l.symbol == "ABCD" and l.series == "EQ"
    assert (l.price_low, l.price_high) == (100.0, 105.0)
    assert l.issue_size_cr == 1250.0 and l.subscription_times == 2.35
    assert l.status == "open" and l.open_date == date(2026, 10, 18)
    future = sources.parse_nse_issue({"companyName": "Later Co", "issueStartDate": "25-Oct-2026", "issueEndDate": "28-Oct-2026", "issuePrice": "50", "series": "SME"}, today)
    assert future.status == "upcoming" and future.series == "SME" and future.price_low == future.price_high == 50.0
    assert sources.parse_nse_issue({"symbol": "X"}) is None


def test_parse_nse_past_and_band_helpers():
    p = sources.parse_nse_past({"symbol": "wxyz", "companyName": "WXYZ Ltd", "issuePrice": "210", "listingDate": "07-Oct-2026"})
    assert p.symbol == "WXYZ.NS" and p.issue_price == 210.0 and p.listing_date == date(2026, 10, 7)
    assert sources._band("Rs. 1,200 - 1,260") == (1200.0, 1260.0)
    assert sources._num("₹ 1,234.5 Cr") == 1234.5


def test_gmp_table_parse_and_match(monkeypatch):
    html = """<table><tr><th>IPO</th><th>Price</th><th>GMP</th></tr>
    <tr><td>Vedagrid Energy Storage IPO</td><td>₹328</td><td>₹58 (17.7%)</td></tr>
    <tr><td>Kaveri Foods IPO (SME)</td><td>Rs.99</td><td>Rs. -4</td></tr></table>"""

    class R:
        text = html
        def raise_for_status(self): pass

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    table = sources.fetch_gmp_table("https://example.com/gmp")
    assert table == {"vedagrid energy storage": 58.0, "kaveri foods": -4.0}
    assert sources.match_gmp(IPOListing(key="V", company="Vedagrid Energy Storage Ltd"), table) == 58.0
    assert sources.match_gmp(IPOListing(key="K", company="Kaveri Foods & Beverages"), table) == -4.0
    assert sources.match_gmp(IPOListing(key="Z", company="Zeta Unrelated"), table) is None
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "ipo_gmp_url", "")
    assert sources.fetch_gmp_table() == {}          # empty setting disables the scrape
    # No header row: second rupee figure is the GMP
    R.text = "<table><tr><td>Nimbus Cloud IPO</td><td>₹148</td><td>₹22</td></tr></table>"
    assert sources.fetch_gmp_table("https://example.com/gmp") == {"nimbus cloud": 22.0}


def test_overrides_apply(tmp_path, monkeypatch):
    from app.config import get_settings
    s = get_settings()
    (s.resolved_data_dir / "ipo_overrides.json").write_text('{"abcd": {"gmp": 12, "lot_size": 70, "fundamentals": {"pe": 30, "industry_pe": 22}}}')
    try:
        l = sources.apply_overrides(IPOListing(key="ABCD", symbol="ABCD", company="ABCD", price_high=100), sources.load_overrides())
        assert l.gmp == 12 and l.gmp_source == "manual" and l.lot_size == 70 and l.fundamentals.pe == 30
        assert l.est_listing_price == 112 and l.gmp_pct == 12.0
    finally:
        (s.resolved_data_dir / "ipo_overrides.json").unlink()


def test_heuristic_assessment_directions():
    strong = IPOListing(key="S", company="Strong Co", price_low=100, price_high=105, issue_size_cr=500, fresh_issue_cr=400, ofs_cr=100, gmp=20,
                        fundamentals=IPOFundamentals(revenue_growth_pct=35, pat_margin_pct=14, debt_equity=0.2, pe=20, industry_pe=28, roe_pct=22, roce_pct=25))
    weak = IPOListing(key="W", company="Weak Co", price_low=100, price_high=105, issue_size_cr=500, fresh_issue_cr=50, ofs_cr=450, gmp=-5,
                      fundamentals=IPOFundamentals(revenue_growth_pct=4, pat_margin_pct=2, debt_equity=1.8, pe=60, industry_pe=30, notes="Top customer concentration 60%"))
    a, b = heuristic_assess(strong, []), heuristic_assess(weak, [], news_score=-0.4)
    assert a.sentiment == "Bullish" and len(a.strengths) == 3 and a.risks
    assert b.sentiment == "Caution" and len(b.risks) == 3
    assert heuristic_assess(IPOListing(key="E", company="Empty Co"), []).sentiment == "Neutral"


def test_service_offline(db):
    cards = upcoming_cards()
    assert len(cards) == 3 and {c.listing.status for c in cards} >= {"open", "upcoming"}
    assert all(c.assessment is not None and len(c.news) == 5 for c in cards)
    listed = recently_listed()
    assert len(listed) == 3 and all(r.ltp and r.issue_price and r.total_gain_pct is not None for r in listed)
    assert listed[0].listing_date >= listed[-1].listing_date


def test_ipo_routes(client):
    html = client.get("/ipo").text
    assert "IPO intelligence" in html and "Vedagrid Energy Storage" in html and "Recently Listed" in html
    assert "GMP unavailable" not in html
    up = client.get("/api/ipo/upcoming").json()
    assert up[0]["listing"]["est_listing_price"] and up[0]["assessment"]["sentiment"] in {"Bullish", "Neutral", "Caution"}
    assert client.get("/api/ipo/listed").json()[0]["symbol"].endswith(".NS")
    assert client.post("/ipo/refresh", follow_redirects=False).status_code == 303


def test_price_trigger_uses_intraday_range():
    e = SpotlightEntry(symbol="X.NS", cutoff_price=100.0, cutoff_direction="above", email="a@b.co")
    assert not price_triggered(e, 98.0)
    assert price_triggered(e, 98.0, day_high=101.0, day_low=95.0)       # touched earlier in the session
    e.cutoff_direction = "below"
    assert price_triggered(e, 103.0, day_high=110.0, day_low=99.5)
    assert not price_triggered(e, 103.0, day_high=110.0, day_low=101.0)
