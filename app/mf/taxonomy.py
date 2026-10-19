"""Mutual fund kinds: plain-language guide content and mapping from AMFI/SEBI category names."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class FundKind:
    id: str
    name: str
    group: str            # Equity | Debt | Hybrid | Other
    use_case: str         # one line
    risk: str             # Low | Low to moderate | Moderate | Moderately high | High | Very high
    horizon: str
    description: str
    patterns: tuple[str, ...]   # regexes matched against the AMFI category header (lower-case)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("patterns")
        return d


KINDS: list[FundKind] = [
    # ---- Debt
    FundKind("overnight", "Overnight fund", "Debt", "Parking money for a few days with almost no risk.", "Low", "1 day to a few weeks",
             "Lends for one day at a time to banks and institutions. Returns track overnight rates; the NAV barely moves. Think of it as a slightly better savings account for very short periods.",
             (r"overnight",)),
    FundKind("liquid", "Liquid fund", "Debt", "Short-term parking: emergency money or cash waiting to be invested.", "Low", "A few weeks to 3 months",
             "Holds very short government and corporate paper (up to 91 days). Money is usually back in your account the next working day. Expect returns a little above a savings account, with small day-to-day movement.",
             (r"liquid", r"money market", r"ultra short")),
    FundKind("short_debt", "Short-duration & corporate bond funds", "Debt", "Steady income for 1 to 3 years without equity swings.", "Low to moderate", "1 to 3 years",
             "Lends to companies and the government for one to three years. Returns are higher than liquid funds but can dip when interest rates rise or a borrower gets into trouble; check credit quality.",
             (r"short duration", r"low duration", r"corporate bond", r"banking and psu", r"floater", r"medium duration", r"credit risk", r"dynamic bond", r"medium to long")),
    FundKind("gilt", "Gilt & long-duration funds", "Debt", "Betting on falling interest rates; no credit risk, but prices swing.", "Moderate", "3 years or more",
             "Holds only government bonds, so there is no default risk, but long bonds move a lot when rates change. Suits investors who understand rate cycles.",
             (r"gilt", r"long duration")),
    # ---- Equity
    FundKind("large_cap", "Large-cap fund", "Equity", "Core long-term equity holding in India's biggest companies.", "High", "5 years or more",
             "Invests at least 80% in the top 100 companies by size. Less volatile than mid or small caps but still equity: expect years with losses. Many investors use an index fund for this slot.",
             (r"large cap", r"large & mid cap", r"large and mid cap")),
    FundKind("mid_cap", "Mid-cap fund", "Equity", "Higher growth potential than large caps, with bigger swings.", "Very high", "7 years or more",
             "Invests in companies ranked 101 to 250 by size. Historically strong long-run returns, but drawdowns of 30 to 40% in bad years are normal. Only for money you will not need for many years.",
             (r"mid cap",)),
    FundKind("small_cap", "Small-cap fund", "Equity", "High risk, high reward; the most volatile equity category.", "Very high", "7 to 10 years or more",
             "Invests in companies ranked 251 and below. Can double in a good cycle and halve in a bad one. Invest gradually (SIP), keep it a small slice of the portfolio, and never money you need soon.",
             (r"small cap",)),
    FundKind("flexi_cap", "Flexi-cap & multi-cap funds", "Equity", "One diversified equity fund where the manager picks across sizes.", "High", "5 years or more",
             "The manager moves between large, mid and small companies as they see fit. A sensible single-fund choice for someone who does not want to manage allocation themselves.",
             (r"flexi cap", r"multi cap", r"focused", r"value", r"contra", r"dividend yield")),
    FundKind("index", "Index funds & ETFs", "Equity", "Lowest-cost way to own the market, e.g. Nifty 50 or Sensex.", "High", "5 years or more",
             "Copies an index instead of trying to beat it, so fees are tiny and there is no manager risk. Returns equal the index minus a small cost. ETFs trade on the exchange like a stock; index funds are bought from the AMC.",
             (r"index fund", r"etf", r"exchange traded", r"fund of funds \(domestic\)", r"fof")),
    FundKind("elss", "ELSS (tax saver)", "Equity", "Equity investing with a tax deduction under Section 80C; 3-year lock-in.", "High", "3-year lock-in, ideally 5+ years",
             "A diversified equity fund that qualifies for the 80C deduction (old tax regime). Each investment is locked for three years, the shortest lock-in among 80C options.",
             (r"elss", r"tax saving", r"equity linked savings")),
    FundKind("sectoral", "Sectoral & thematic funds", "Equity", "Concentrated bets on one sector or theme, such as banking or infrastructure.", "Very high", "5 years or more, with timing risk",
             "Everything rides on one sector or theme, so the fund can lead or lag the market for years. Treat as a satellite position, not a core holding.",
             (r"sectoral", r"thematic", r"sector", r"infrastructure", r"banking & financial", r"pharma", r"technology", r"consumption", r"psu", r"business cycle", r"esg", r"quant")),
    FundKind("international", "International funds", "Equity", "Exposure to global companies and a hedge against the rupee.", "Very high", "5 years or more",
             "Invests abroad, often through a feeder into a foreign fund or an index like the S&P 500 or Nasdaq 100. Adds currency and geopolitical risk; taxed like debt for shorter holding periods.",
             (r"overseas", r"international", r"global", r"foreign", r"fund of funds \(overseas", r"us equity", r"nasdaq", r"s&p")),
    # ---- Hybrid
    FundKind("hybrid_conservative", "Conservative hybrid funds", "Hybrid", "Mostly debt with a small equity kicker for cautious investors.", "Moderate", "3 years or more",
             "Holds 75 to 90% debt and the rest in equity. Smoother than equity funds, a bit more return than pure debt. A gentle first step away from fixed deposits.",
             (r"conservative hybrid", r"equity savings")),
    FundKind("hybrid_balanced", "Balanced advantage & aggressive hybrid", "Hybrid", "One fund that balances equity and debt for you.", "Moderately high", "3 to 5 years or more",
             "Aggressive hybrids keep 65 to 80% in equity; balanced advantage funds shift the mix based on market valuations. Good for investors who want equity growth with a cushion.",
             (r"balanced advantage", r"dynamic asset allocation", r"aggressive hybrid", r"balanced hybrid", r"multi asset", r"arbitrage")),
    # ---- Other
    FundKind("gold", "Gold & silver funds", "Other", "Portfolio diversifier and inflation hedge without storing metal.", "Moderately high", "3 to 5 years or more",
             "Tracks the price of gold or silver through ETFs or funds of funds. Prices can stagnate for years, so keep it to a modest allocation.",
             (r"gold", r"silver", r"commodit")),
    FundKind("solution", "Retirement & children's funds", "Other", "Goal-based funds with a lock-in to enforce discipline.", "Moderately high", "5 years or more",
             "Solution-oriented schemes with lock-ins of five years or until retirement or the child turns 18. The lock-in is the feature: it stops impulsive withdrawals.",
             (r"retirement", r"children", r"solution oriented")),
    FundKind("other", "Other schemes", "Other", "Closed-ended, interval and other categories.", "Varies", "Varies",
             "Schemes that do not fit the standard open-ended categories, including closed-ended and interval funds. Check the scheme document before investing.",
             ()),
]

KIND_BY_ID = {k.id: k for k in KINDS}
GROUP_ORDER = ["Equity", "Hybrid", "Debt", "Other"]

_PRIORITY = ("gold", "international", "solution", "elss", "sectoral")  # checked first: their categories are generic


def classify(amfi_category: str, scheme_name: str = "") -> str:
    """Map an AMFI section header such as 'Open Ended Schemes(Equity Scheme - Large Cap Fund)' to a kind id.
    The scheme name breaks ties for generic categories (FoF, Other ETFs), e.g. gold or overseas feeders."""
    text = (amfi_category or "").lower()
    name = (scheme_name or "").lower()
    if re.search(r"\b(gold|silver)\b", name):
        return "gold"
    if re.search(r"nasdaq|s&p|\bus\b|u\.s\.|international|global|overseas|world|china|japan|europe|emerging", name):
        return "international"
    ordered = [KIND_BY_ID[i] for i in _PRIORITY] + [k for k in KINDS if k.id not in _PRIORITY]
    for kind in ordered:
        for pat in kind.patterns:
            if re.search(pat, text):
                return kind.id
    if "equity" in text:
        return "flexi_cap"
    if "debt" in text or "income" in text:
        return "short_debt"
    if "hybrid" in text:
        return "hybrid_balanced"
    return "other"
