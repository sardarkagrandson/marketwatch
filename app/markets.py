"""Market profiles: everything that differs between exchanges lives here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time as dtime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketProfile:
    id: str                     # IN | ZA
    name: str                   # India | South Africa
    exchange: str               # NSE / BSE | JSE
    flag: str
    currency: str               # INR | ZAR
    currency_symbol: str        # ₹ | R
    tz: str
    pre_open: dtime
    open: dtime
    close: dtime
    post_close: dtime
    suffixes: tuple[str, ...]   # Yahoo suffixes that belong to this market
    default_suffix: str
    symbols_file: str           # bundled JSON map for search / resolution
    indices: tuple[tuple[str, str], ...]
    popular: tuple[str, ...]
    news_locale: dict           # Google News RSS parameters
    price_divisor: float = 1.0  # Yahoo quotes JSE equities in cents (ZAc): divide by 100
    live_quotes: bool = False   # exchange-native quote provider available (NSE via nsemine)
    modules: tuple[str, ...] = ()   # extra modules shown in the navigation
    hero_title: str = ""
    hero_lead: str = ""
    search_placeholder: str = ""
    sample_queries: tuple[str, ...] = ()
    disclaimer_regulator: str = "a registered investment advisor"
    static_holidays: dict[int, tuple[str, ...]] = field(default_factory=dict)

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    def is_mine(self, symbol: str) -> bool:
        return symbol.upper().endswith(self.suffixes)


INDIA = MarketProfile(
    id="IN", name="India", exchange="NSE / BSE", flag="\U0001F1EE\U0001F1F3", currency="INR", currency_symbol="₹",
    tz="Asia/Kolkata", pre_open=dtime(9, 0), open=dtime(9, 15), close=dtime(15, 30), post_close=dtime(16, 0),
    suffixes=(".NS", ".BO"), default_suffix=".NS", symbols_file="nse_symbols.json",
    indices=(("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"), ("^NSEBANK", "NIFTY Bank"), ("^CNXIT", "NIFTY IT")),
    popular=("RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "TATAMOTORS.NS", "SBIN.NS", "BHARTIARTL.NS"),
    news_locale={"hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
    live_quotes=True, modules=("mf", "ipo"),
    hero_title="Know what Dalal Street is whispering before you act.",
    hero_lead="Search any listed company to see live price action, 7-day news scored for sentiment and impact, technical setups, and the statistical odds of a price reaching your target.",
    search_placeholder="Search NSE / BSE stocks, e.g. Tata Motors or INFY.NS",
    sample_queries=("Tata Motors", "HDFC Bank", "INFY.NS"),
    disclaimer_regulator="a SEBI-registered advisor",
)

# JSE trades 09:00-17:00 SAST with no lunch break. South African public holidays; a holiday on a
# Sunday moves to the Monday. Extend or override with MARKET_HOLIDAYS_ZA in .env.
SOUTH_AFRICA = MarketProfile(
    id="ZA", name="South Africa", exchange="JSE", flag="\U0001F1FF\U0001F1E6", currency="ZAR", currency_symbol="R",
    tz="Africa/Johannesburg", pre_open=dtime(8, 30), open=dtime(9, 0), close=dtime(17, 0), post_close=dtime(17, 30),
    suffixes=(".JO",), default_suffix=".JO", symbols_file="jse_symbols.json",
    indices=(("^J203.JO", "All Share"), ("^J200.JO", "Top 40"), ("^J210.JO", "Resources 10"), ("^J212.JO", "Financials 15")),
    popular=("NPN.JO", "PRX.JO", "FSR.JO", "SBK.JO", "CPI.JO", "MTN.JO", "SOL.JO", "AGL.JO"),
    news_locale={"hl": "en-ZA", "gl": "ZA", "ceid": "ZA:en"},
    price_divisor=100.0, live_quotes=False, modules=(),
    hero_title="Know what the JSE floor is whispering before you act.",
    hero_lead="Search any JSE-listed company to see price action, 7-day news scored for sentiment and impact, technical setups, and the statistical odds of a price reaching your target.",
    search_placeholder="Search JSE stocks, e.g. Naspers or SOL.JO",
    sample_queries=("Naspers", "Standard Bank", "SOL.JO"),
    disclaimer_regulator="an FSCA-authorised financial advisor",
    static_holidays={
        2026: ("2026-01-01", "2026-03-21", "2026-04-03", "2026-04-06", "2026-04-27", "2026-05-01", "2026-06-16",
               "2026-08-10", "2026-09-24", "2026-12-16", "2026-12-25", "2026-12-26"),
        2027: ("2027-01-01", "2027-03-22", "2027-03-26", "2027-03-29", "2027-04-27", "2027-05-01", "2027-06-16",
               "2027-08-09", "2027-09-24", "2027-12-16", "2027-12-25", "2027-12-27"),
    },
)

MARKETS: dict[str, MarketProfile] = {m.id: m for m in (INDIA, SOUTH_AFRICA)}
DEFAULT_MARKET = "IN"


def get_market(market_id: str | None) -> MarketProfile:
    return MARKETS.get((market_id or "").upper(), MARKETS[DEFAULT_MARKET])


def market_for_symbol(symbol: str | None, fallback: str = DEFAULT_MARKET) -> MarketProfile:
    sym = (symbol or "").upper()
    for m in MARKETS.values():
        if m.is_mine(sym):
            return m
    return get_market(fallback)
