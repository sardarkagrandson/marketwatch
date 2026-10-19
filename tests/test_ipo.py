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
    assert l.issue_shares == 12_500_000_000 and l.issue_size_cr == round(12_500_000_000 * 105 / 1e7, 2) and l.subscription_times == 2.35
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
    <tr><td>Kaveri Foods IPO (SME)</td><td>Rs.99</td><td>Rs. -4</td></tr>
    <tr><td>Nifty 50</td><td>24,000</td><td>₹8377</td></tr></table>"""

    class R:
        text = html
        content = html.encode()
        status_code = 200
        url = "https://example.com/gmp"
        def raise_for_status(self): pass

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    table = sources.fetch_gmp_table("https://example.com/gmp")
    assert table == {"vedagrid energy storage": 58.0, "kaveri foods": -4.0}
    assert sources.match_gmp(IPOListing(key="V", company="Vedagrid Energy Storage Ltd", price_high=328), table) == 58.0
    assert sources.match_gmp(IPOListing(key="K", company="Kaveri Foods & Beverages", price_high=99), table) == -4.0
    # implausible premium relative to the band is rejected
    assert sources.match_gmp(IPOListing(key="N", company="Nifty 50", price_high=700), table) is None
    assert sources.match_gmp(IPOListing(key="Z", company="Zeta Unrelated"), table) is None
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "ipo_gmp_url", "")
    assert sources.fetch_gmp_table() == {}          # empty setting disables the scrape
    # Without a header row naming the GMP column nothing is parsed (safer than guessing)
    R.text = "<table><tr><td>Nimbus Cloud IPO</td><td>₹148</td><td>₹22</td></tr></table>"
    assert sources.fetch_gmp_table("https://example.com/gmp") == {}


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
    assert html.count("GMP unavailable") == 1  # footnote only; every demo card has a GMP pill
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


def test_expected_dates_and_accordion(client, db):
    from app.ipo.service import upcoming_listings
    rows = upcoming_listings()
    for r in rows:
        assert r.allotment_date and r.listing_date and r.listing_date > r.close_date
        assert r.listing_date.weekday() < 5 and r.dates_estimated
    html = client.get("/ipo").text
    assert html.count('<details class="card ipo-card') == 3 and "Bidding opens" in html and "(est.)" in html


def test_listed_without_price_data(monkeypatch):
    from app.ipo.schemas import ListedIPO
    from app.ipo import service
    from app.market import data

    class Broken:
        name = "broken"
        def history(self, *a, **k): raise LookupError("No price history returned")
        def quote(self, *a, **k): raise LookupError("nope")

    data.set_engine(data.MarketDataEngine(Broken()))
    try:
        r = service._performance(ListedIPO(key="X", symbol="X.NS", company="X Ltd", issue_price=100))
        assert r.ltp is None and r.chart_symbol is None and "No price data yet" in r.error
    finally:
        data.set_engine(None)


def test_gmp_multiple_urls(monkeypatch):
    import httpx
    calls = []

    class R:
        status_code = 200
        def __init__(self, url):
            self.url = url
            self.text = "<p>nothing</p>" if "first" in url else "<table><tr><th>IPO</th><th>GMP</th></tr><tr><td>Alpha Metals IPO</td><td>₹12</td></tr></table>"
            self.content = self.text.encode()
        def raise_for_status(self): pass

    monkeypatch.setattr(httpx, "get", lambda url, **k: (calls.append(url), R(url))[1])
    table = sources.fetch_gmp_table("https://first.example/gmp, https://second.example/gmp")
    assert table == {"alpha metals": 12.0} and len(calls) == 2
    assert len(sources.gmp_diagnostics()["attempts"]) == 2


REAL_GMP_HTML = """<table><thead><tr><th>Name &#9650; &#9660;</th><th>GMP &#9650; &#9660;</th><th>&#128293;Rating</th><th>Sub</th><th>Price (&#8377;)</th><th>IPO Size</th><th>Lot</th><th>Open</th></tr></thead>
<tbody>
<tr><td><a>BLS Polymers IPO</a> <span>U</span></td><td>&#8377; 20 (13.33%) 20 &#8595; / 20 &#8593;</td><td>&#128293;</td><td>-</td><td>150</td><td>&#8377;255.00 Cr</td><td>100</td><td>27-Oct</td></tr>
<tr><td>Core4 Engineers BSE SME U</td><td>&#8377; -- (0.00%) 0 &#8595; / 0 &#8593;</td><td>&#128293;</td><td>-</td><td>93</td><td>&#8377;54.82 Cr</td><td>1,200</td><td>23-Oct</td></tr>
<tr><td>Jio Platforms IPO U</td><td>&#8377; 252 (22.52%) 148 &#8595; / 252 &#8593;</td><td>x</td><td>-</td><td>1,119</td><td>&#8377;30213.00 Cr</td><td>12</td><td>21-Oct</td></tr>
<tr><td>Tonbo Imaging India IPO CT</td><td>&#8377; 515 (73.57%) 270 &#8595; / 516 &#8593;</td><td>x</td><td>37.55x</td><td>700</td><td>&#8377;852.18 Cr</td><td>21</td><td>15-Oct GMP: 500</td></tr>
</tbody></table>"""


def test_gmp_parse_real_page_layout(monkeypatch):
    class R:
        text = REAL_GMP_HTML
        content = REAL_GMP_HTML.encode()
        status_code = 200
        url = "https://example.com/gmp"
        def raise_for_status(self): pass

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    table = sources.fetch_gmp_table("https://example.com/gmp")
    assert table == {"bls polymers": 20.0, "jio platforms": 252.0, "tonbo imaging india": 515.0}
    tonbo = IPOListing(key="TONBO", symbol="TONBO", company="Tonbo Imaging India Limited", price_low=665, price_high=700)
    jio = IPOListing(key="JPL", symbol="JPL", company="Jio Platforms Limited", price_low=1065, price_high=1119)
    other = IPOListing(key="X", symbol="X", company="Tonbo Imaging India Limited", price_low=100, price_high=120)
    assert sources.match_gmp(tonbo, table) == 515.0
    assert sources.match_gmp(jio, table) == 252.0
    assert sources.match_gmp(other, table) is None          # price on the page disagrees with the band


def test_parse_real_nse_current_issue_row():
    row = {"companyName": "Tonbo Imaging India Limited", "issueEndDate": "19-Oct-2026", "issuePrice": "Rs.665 to Rs.700",
           "issueSize": "8526033", "issueStartDate": "15-Oct-2026", "series": "EQ", "status": "Active", "symbol": "TONBO",
           "category": "Total", "noOfSharesOffered": "8526033.0", "noOfTime": "96.38560230766173", "noOfsharesBid": "8.21786826E8", "srNo": None}
    l = sources.parse_nse_issue(row, date(2026, 10, 17))
    assert (l.price_low, l.price_high) == (665.0, 700.0) and l.status == "open"
    assert l.issue_shares == 8526033 and l.issue_size_cr == round(8526033 * 700 / 1e7, 2)
    assert round(l.subscription_times, 2) == 96.39


def test_assessment_recomputes_when_inputs_change(db):
    from app.ipo import service
    from app.ipo.schemas import IPOListing
    base = IPOListing(key="RECALC", company="Recalc Co", price_low=100, price_high=110, gmp=5)
    a1, _ = service._assessment_for(base, [], 0.0)
    a2, _ = service._assessment_for(base.model_copy(update={"gmp": 60, "subscription_times": 40.0}), [], 0.0)
    assert a1.strengths != a2.strengths or a1.sentiment != a2.sentiment
    service.clear_ipo_cache()
    from app.models import IPOCache
    assert db.query(IPOCache).filter(IPOCache.key.like("ipo:%")).count() == 0
