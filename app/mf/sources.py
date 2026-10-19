"""Mutual fund data: AMFI daily NAV file (all schemes, official categories) and mfapi.in NAV history."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from pydantic import BaseModel

from app.mf.taxonomy import classify

log = logging.getLogger(__name__)

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
MFAPI_URL = "https://api.mfapi.in/mf/{code}"
USER_AGENT = "Mozilla/5.0 (compatible; SnitchofDalal/0.1)"


class Scheme(BaseModel):
    code: str
    name: str
    amc: str
    amfi_category: str
    kind: str
    nav: float | None = None
    nav_date: date | None = None
    isin: str | None = None
    direct: bool = False
    growth: bool = False


# ---------------------------------------------------------------- AMFI parse
def _plan_flags(name: str) -> tuple[bool, bool]:
    low = name.lower()
    direct = "direct" in low
    growth = ("growth" in low or "cumulative" in low) and not any(w in low for w in ("idcw", "dividend", "payout", "reinvest"))
    return direct, growth


def _date(s: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_amfi(text: str) -> list[Scheme]:
    """Parse NAVAll.txt. Section headers name the category; AMC lines have no ';'; scheme rows have 6 fields."""
    schemes: list[Scheme] = []
    category = ""
    amc = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            if "schemes" in line.lower() and "(" in line:
                category = line
            else:
                amc = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue  # header row or malformed
        code, isin1, _isin2, name, nav_s, date_s = parts[:6]
        try:
            nav = float(nav_s) if nav_s not in ("", "N.A.", "-") else None
        except ValueError:
            nav = None
        direct, growth = _plan_flags(name)
        schemes.append(Scheme(
            code=code, name=re.sub(r"\s+", " ", name), amc=amc, amfi_category=category, kind=classify(category, name),
            nav=nav, nav_date=_date(date_s), isin=isin1 or None, direct=direct, growth=growth,
        ))
    return schemes


def fetch_amfi() -> list[Scheme]:
    import httpx

    resp = httpx.get(AMFI_NAV_URL, timeout=40, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    schemes = parse_amfi(resp.text)
    if len(schemes) < 100:
        raise RuntimeError(f"AMFI file looked wrong ({len(schemes)} schemes parsed)")
    return schemes


# ---------------------------------------------------------------- history
def fetch_history(code: str) -> tuple[dict, list[tuple[date, float]]]:
    """Return (meta, [(date, nav), ...] oldest first) from mfapi.in."""
    import httpx

    resp = httpx.get(MFAPI_URL.format(code=code), timeout=30, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    payload = resp.json()
    rows = []
    for item in payload.get("data", []):
        d = _date(str(item.get("date", "")))
        try:
            nav = float(item.get("nav"))
        except (TypeError, ValueError):
            continue
        if d and nav > 0:
            rows.append((d, nav))
    rows.sort(key=lambda r: r[0])
    return payload.get("meta", {}), rows


# ---------------------------------------------------------------- demo data
_DEMO = [
    ("100001", "Demo Overnight Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Debt Scheme - Overnight Fund)", 1310.5, 0.065, 0.002),
    ("100002", "Demo Liquid Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Debt Scheme - Liquid Fund)", 3412.8, 0.07, 0.004),
    ("100003", "Demo Corporate Bond Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Debt Scheme - Corporate Bond Fund)", 28.4, 0.075, 0.02),
    ("100004", "Demo Gilt Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Debt Scheme - Gilt Fund)", 61.2, 0.07, 0.05),
    ("100005", "Demo Bluechip Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Equity Scheme - Large Cap Fund)", 88.9, 0.13, 0.16),
    ("100006", "Demo Nifty 50 Index Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Other Scheme - Index Funds)", 24.1, 0.125, 0.15),
    ("100007", "Demo Midcap Opportunities - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Equity Scheme - Mid Cap Fund)", 142.3, 0.17, 0.22),
    ("100008", "Demo Small Cap Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Equity Scheme - Small Cap Fund)", 176.0, 0.19, 0.28),
    ("100009", "Demo Flexi Cap Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Equity Scheme - Flexi Cap Fund)", 67.5, 0.15, 0.18),
    ("100010", "Demo Tax Saver Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Equity Scheme - ELSS)", 112.7, 0.145, 0.18),
    ("100011", "Demo Balanced Advantage Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Hybrid Scheme - Dynamic Asset Allocation or Balanced Advantage)", 19.8, 0.11, 0.09),
    ("100012", "Demo Conservative Hybrid Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Hybrid Scheme - Conservative Hybrid Fund)", 31.6, 0.085, 0.04),
    ("100013", "Demo Gold ETF Fund of Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Other Scheme - FoF Domestic)", 22.9, 0.10, 0.14),
    ("100014", "Demo Banking & Financial Services Fund - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Equity Scheme - Sectoral/ Thematic)", 54.3, 0.14, 0.24),
    ("100015", "Demo US Equity FoF - Direct Plan - Growth", "Demo Asset Management", "Open Ended Schemes(Other Scheme - FoF Overseas)", 38.2, 0.13, 0.2),
    ("100016", "Demo Bluechip Fund - Regular Plan - IDCW", "Demo Asset Management", "Open Ended Schemes(Equity Scheme - Large Cap Fund)", 24.4, 0.12, 0.16),
]


def demo_schemes() -> list[Scheme]:
    out = []
    for code, name, amc, cat, nav, _, _ in _DEMO:
        d, g = _plan_flags(name)
        out.append(Scheme(code=code, name=name, amc=amc, amfi_category=cat, kind=classify(cat, name), nav=nav,
                          nav_date=date.today(), direct=d, growth=g))
    return out


def demo_history(code: str) -> tuple[dict, list[tuple[date, float]]]:
    import numpy as np

    row = next((r for r in _DEMO if r[0] == code), None)
    if row is None:
        return {}, []
    _, name, amc, cat, nav, annual, vol = row
    rng = np.random.default_rng(int(code))
    days = 252 * 6
    rets = rng.normal(annual / 252, vol / np.sqrt(252), days)
    path = nav / float(np.exp(rets.sum())) * np.exp(np.cumsum(rets))
    today = date.today()
    dates = [today - timedelta(days=int(i * 365 / 252)) for i in range(days - 1, -1, -1)]
    return {"scheme_name": name, "fund_house": amc, "scheme_category": cat}, list(zip(dates, [float(v) for v in path]))
