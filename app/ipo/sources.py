"""IPO data sources: NSE public JSON, optional GMP page, operator overrides, offline demo."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta

from app.config import get_settings
from app.ipo.schemas import IPOFundamentals, IPOListing, ListedIPO

log = logging.getLogger(__name__)

NSE_UPCOMING = "https://www.nseindia.com/api/all-upcoming-issues?category=ipo"
NSE_CURRENT = "https://www.nseindia.com/api/ipo-current-issue"
NSE_PAST = "https://www.nseindia.com/api/public-past-issues"
OVERRIDES_FILE = "ipo_overrides.json"


# ---------------------------------------------------------------- parsing helpers
def _date(v) -> date | None:
    if not v:
        return None
    if isinstance(v, (date, datetime)):
        return v if isinstance(v, date) else v.date()
    s = str(v).strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _num(v) -> float | None:
    if v is None:
        return None
    s = re.sub(r"[^0-9.\-]", "", str(v).replace(",", ""))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _band(v) -> tuple[float | None, float | None]:
    """'100 to 105' / '100-105' / '105' -> (100, 105)."""
    if v is None:
        return None, None
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(v).replace(",", ""))]
    if not nums:
        return None, None
    if len(nums) == 1:
        return nums[0], nums[0]
    return min(nums[:2]), max(nums[:2])


def _get(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, "", "-"):
            return d[k]
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, "", "-"):
            return v
    return default


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _status(open_d: date | None, close_d: date | None, today: date) -> str:
    if open_d and close_d:
        if open_d <= today <= close_d:
            return "open"
        if today > close_d:
            return "closed"
    return "upcoming"


def parse_nse_issue(row: dict, today: date | None = None) -> IPOListing | None:
    today = today or date.today()
    company = _get(row, "companyName", "company", "name")
    if not company:
        return None
    symbol = _get(row, "symbol")
    open_d = _date(_get(row, "issueStartDate", "openDate", "issueOpenDate"))
    close_d = _date(_get(row, "issueEndDate", "closeDate", "issueCloseDate"))
    lo, hi = _band(_get(row, "issuePrice", "priceBand", "price"))
    size = _num(_get(row, "issueSize", "issueSizeCr", "size"))
    # NSE reports issue size either in crore or in rupees; normalise anything implausibly big.
    if size and size > 1e6:
        size = round(size / 1e7, 2)
    series = str(_get(row, "series", default="EQ")).upper()
    series = "SME" if "SME" in series else "EQ"
    return IPOListing(
        key=str(symbol or _slug(company)).upper(),
        symbol=str(symbol).upper() if symbol else None,
        company=str(company).strip(),
        series=series,
        open_date=open_d,
        close_date=close_d,
        price_low=lo,
        price_high=hi,
        lot_size=int(_num(_get(row, "lotSize", "marketLot", "minBidQty")) or 0) or None,
        issue_size_cr=size,
        subscription_times=_num(_get(row, "noOfTimes", "subscriptionTimes", "timesSubscribed")),
        status=_status(open_d, close_d, today) if _get(row, "status", default="").lower() != "active" else "open",
    )


def parse_nse_past(row: dict) -> ListedIPO | None:
    company = _get(row, "companyName", "company", "name")
    symbol = _get(row, "symbol")
    if not company or not symbol:
        return None
    _, issue_price = _band(_get(row, "issuePrice", "price"))
    series = str(_get(row, "series", default="EQ")).upper()
    return ListedIPO(
        key=str(symbol).upper(),
        symbol=f"{str(symbol).upper()}.NS",
        company=str(company).strip(),
        series="SME" if "SME" in series else "EQ",
        issue_price=issue_price,
        listing_date=_date(_get(row, "listingDate", "dateOfListing", "listing_date")),
    )


# ---------------------------------------------------------------- NSE fetch
def _nse_json(url: str):
    from nsemine.bin import scraper

    resp = scraper.get_request(url=url)
    if resp is None:
        raise RuntimeError(f"NSE returned no response for {url}")
    data = resp.json()
    if isinstance(data, dict):
        for k in ("data", "upcomingIssues", "currentIssues", "pastIssues"):
            if isinstance(data.get(k), list):
                return data[k]
        return []
    return data


def fetch_nse_upcoming() -> list[IPOListing]:
    rows: list[IPOListing] = []
    seen: set[str] = set()
    for url in (NSE_CURRENT, NSE_UPCOMING):
        try:
            for raw in _nse_json(url):
                item = parse_nse_issue(raw)
                if item and item.key not in seen:
                    seen.add(item.key)
                    rows.append(item)
        except Exception as exc:
            log.warning("NSE IPO fetch failed (%s): %s", url, exc)
    return rows


def fetch_nse_past(days: int = 60) -> list[ListedIPO]:
    cutoff = date.today() - timedelta(days=days)
    out: list[ListedIPO] = []
    try:
        for raw in _nse_json(NSE_PAST):
            item = parse_nse_past(raw)
            if item and (item.listing_date is None or item.listing_date >= cutoff):
                out.append(item)
    except Exception as exc:
        log.warning("NSE past issues fetch failed: %s", exc)
    return out


# ---------------------------------------------------------------- GMP (unofficial)
def fetch_gmp_table(url: str | None = None) -> dict[str, float]:
    """Best-effort parse of a public grey-market-premium table into {normalised company: gmp}.

    Grey market premiums are unofficial, unregulated indications and change hourly.
    The page layout is outside our control, so this returns {} on any failure.
    """
    url = url or get_settings().ipo_gmp_url
    if not url:
        return {}
    import httpx

    out: dict[str, float] = {}
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; SnitchofDalalBot/0.1)"})
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        log.warning("GMP fetch failed: %s", exc)
        return {}
    # Walk table rows. Use the header row to locate the GMP column when there is one;
    # otherwise fall back to the second rupee figure in the row (first is usually the price).
    rupee = re.compile(r"(?:₹|Rs\.?)\s*(-?\d+(?:\.\d+)?)")
    gmp_col: int | None = None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        cells = [re.sub(r"<[^>]+>", " ", c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S | re.I)]
        cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
        if len(cells) < 2:
            continue
        if gmp_col is None and any("gmp" in c.lower() for c in cells):
            gmp_col = next(i for i, c in enumerate(cells) if "gmp" in c.lower())
            continue
        name = cells[0]
        gmp = None
        if gmp_col is not None and gmp_col < len(cells):
            m = rupee.search(cells[gmp_col]) or re.search(r"(-?\d+(?:\.\d+)?)", cells[gmp_col])
            gmp = float(m.group(1)) if m else None
        else:
            figures = [float(m.group(1)) for c in cells[1:] for m in [rupee.search(c)] if m]
            gmp = figures[1] if len(figures) >= 2 else (figures[0] if figures else None)
        if name and gmp is not None and len(name) > 3:
            out[_norm_company(name)] = gmp
    return out


def _norm_company(s: str) -> str:
    s = re.sub(r"\b(ipo|ltd|limited|sme|nse|bse|pvt|private)\b", " ", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def match_gmp(listing: IPOListing, table: dict[str, float]) -> float | None:
    if not table:
        return None
    import difflib

    target = _norm_company(listing.company)
    if target in table:
        return table[target]
    for name, gmp in table.items():  # "kaveri foods" vs "kaveri foods beverages"
        if len(name) >= 6 and (target.startswith(name) or name.startswith(target)):
            return gmp
    hit = difflib.get_close_matches(target, list(table), n=1, cutoff=0.75)
    return table[hit[0]] if hit else None


# ---------------------------------------------------------------- operator overrides
def load_overrides() -> dict:
    """Optional JSON in the data dir keyed by symbol or company name:
    {"ABCD": {"gmp": 45, "lot_size": 150, "fresh_issue_cr": 500, "ofs_cr": 200,
              "fundamentals": {"revenue_growth_pct": 22, "pat_margin_pct": 11, "debt_equity": 0.3,
                               "pe": 28, "industry_pe": 24, "roe_pct": 18, "roce_pct": 21, "notes": "..."},
              "issue_price": 105, "listing_date": "2026-10-02", "symbol": "ABCD"}}"""
    path = get_settings().resolved_data_dir / OVERRIDES_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k).strip().upper(): v for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("ipo_overrides.json unreadable: %s", exc)
        return {}


def apply_overrides(listing: IPOListing, overrides: dict) -> IPOListing:
    o = overrides.get(listing.key) or overrides.get((listing.symbol or "").upper()) or overrides.get(listing.company.upper())
    if not o:
        return listing
    data = listing.model_dump()
    for k in ("gmp", "lot_size", "fresh_issue_cr", "ofs_cr", "issue_size_cr", "subscription_times", "price_low", "price_high"):
        if o.get(k) is not None:
            data[k] = o[k]
    if o.get("gmp") is not None:
        data["gmp_source"] = "manual"
    if isinstance(o.get("fundamentals"), dict):
        data["fundamentals"] = IPOFundamentals(**{**listing.fundamentals.model_dump(), **o["fundamentals"]}).model_dump()
    return IPOListing(**data)


# ---------------------------------------------------------------- offline demo data
def demo_upcoming(today: date | None = None) -> list[IPOListing]:
    today = today or date.today()
    return [
        IPOListing(key="VEDAGRID", symbol="VEDAGRID", company="Vedagrid Energy Storage", series="EQ",
                   open_date=today - timedelta(days=1), close_date=today + timedelta(days=1), price_low=312, price_high=328,
                   lot_size=45, issue_size_cr=1850, fresh_issue_cr=1200, ofs_cr=650, subscription_times=3.4,
                   gmp=58, gmp_source="demo",
                   fundamentals=IPOFundamentals(revenue_growth_pct=41, pat_margin_pct=9.5, debt_equity=0.6, pe=34, industry_pe=27, roe_pct=17, roce_pct=19,
                                                notes="Utility-scale battery storage; order book 2.1x FY26 revenue.")),
        IPOListing(key="KAVERIFOODS", symbol="KAVERIFOODS", company="Kaveri Foods & Beverages", series="EQ",
                   open_date=today + timedelta(days=3), close_date=today + timedelta(days=5), price_low=94, price_high=99,
                   lot_size=150, issue_size_cr=620, fresh_issue_cr=220, ofs_cr=400, gmp=-4, gmp_source="demo",
                   fundamentals=IPOFundamentals(revenue_growth_pct=8, pat_margin_pct=4.1, debt_equity=1.4, pe=52, industry_pe=38, roe_pct=9, roce_pct=11,
                                                notes="Mostly OFS by promoters; top customer 46% of revenue.")),
        IPOListing(key="NIMBUSTECH", symbol="NIMBUSTECH", company="Nimbus Cloud Technologies", series="SME",
                   open_date=today + timedelta(days=6), close_date=today + timedelta(days=8), price_low=140, price_high=148,
                   lot_size=1000, issue_size_cr=48, fresh_issue_cr=48, ofs_cr=0, gmp=22, gmp_source="demo",
                   fundamentals=IPOFundamentals(revenue_growth_pct=65, pat_margin_pct=14, debt_equity=0.1, pe=25, industry_pe=30, roe_pct=24, roce_pct=28)),
    ]


def demo_past(today: date | None = None) -> list[ListedIPO]:
    today = today or date.today()
    return [
        ListedIPO(key="ARJUNRAIL", symbol="ARJUNRAIL.NS", company="Arjun Rail Infra", issue_price=210, listing_date=today - timedelta(days=12)),
        ListedIPO(key="SOLARISPHARMA", symbol="SOLARISPHARMA.NS", company="Solaris Pharma Labs", issue_price=540, listing_date=today - timedelta(days=25)),
        ListedIPO(key="DESIKART", symbol="DESIKART.NS", company="DesiKart E-Commerce", issue_price=76, listing_date=today - timedelta(days=41), series="SME"),
    ]
