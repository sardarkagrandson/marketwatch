"""Fundamental catalyst & risk evaluator: structured LLM completion with a rules fallback."""
from __future__ import annotations

import logging

from app.config import get_settings
from app.ipo.schemas import IPOAssessment, IPOListing

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an equity analyst evaluating an upcoming Indian IPO for a retail investor.
Use only the facts provided (issue details, DRHP summary metrics, grey market premium, recent headlines).
Produce exactly three core strengths and exactly three key risks, each a concrete sentence citing a number
or fact from the input where possible. Sentiment: Bullish only with clear growth, reasonable valuation and
positive news; Caution when valuation is stretched, leverage is high, the issue is mostly OFS, or legal /
concentration risks exist; otherwise Neutral. Never give buy/sell advice."""


def _fundamentals_text(l: IPOListing) -> str:
    f = l.fundamentals
    parts = []
    if f.revenue_growth_pct is not None: parts.append(f"revenue growth {f.revenue_growth_pct:.1f}%")
    if f.pat_margin_pct is not None: parts.append(f"PAT margin {f.pat_margin_pct:.1f}%")
    if f.debt_equity is not None: parts.append(f"debt/equity {f.debt_equity:.2f}")
    if f.pe is not None: parts.append(f"post-issue P/E {f.pe:.1f}" + (f" vs industry {f.industry_pe:.1f}" if f.industry_pe else ""))
    if f.roe_pct is not None: parts.append(f"ROE {f.roe_pct:.1f}%")
    if f.roce_pct is not None: parts.append(f"ROCE {f.roce_pct:.1f}%")
    if f.notes: parts.append(f"notes: {f.notes}")
    return "; ".join(parts) if parts else "no DRHP summary available"


def _issue_text(l: IPOListing) -> str:
    band = f"Rs {l.price_low:g}-{l.price_high:g}" if l.price_low and l.price_high else "price band n/a"
    size = f"issue size Rs {l.issue_size_cr:g} cr" if l.issue_size_cr else "issue size n/a"
    mix = ""
    if l.fresh_issue_cr is not None or l.ofs_cr is not None:
        mix = f" (fresh Rs {l.fresh_issue_cr or 0:g} cr, OFS Rs {l.ofs_cr or 0:g} cr)"
    gmp = f"GMP Rs {l.gmp:+g} ({l.gmp_pct:+.1f}%)" if l.gmp is not None and l.gmp_pct is not None else "GMP n/a"
    sub = f", subscribed {l.subscription_times:.1f}x" if l.subscription_times else ""
    return f"{l.company} ({l.series}); {band}; {size}{mix}; {gmp}{sub}"


# ---------------------------------------------------------------- LLM
def llm_assess(listing: IPOListing, headlines: list[str]) -> IPOAssessment:
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)
    news = "\n".join(f"- {h}" for h in headlines[:5]) or "- (no recent headlines)"
    user = f"Issue: {_issue_text(listing)}\nDRHP summary: {_fundamentals_text(listing)}\nHeadlines (last 14 days):\n{news}"
    try:
        response = client.beta.messages.parse(
            model=settings.sentiment_model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_format=IPOAssessment,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as exc:
        raise RuntimeError(f"LLM rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"LLM API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(f"LLM connection error: {exc}") from exc
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError("LLM declined to assess the IPO")
    return response.parsed_output


# ---------------------------------------------------------------- rules fallback
def heuristic_assess(listing: IPOListing, headlines: list[str], news_score: float | None = None) -> IPOAssessment:
    f = listing.fundamentals
    strengths: list[str] = []
    risks: list[str] = []
    score = 0.0

    if f.revenue_growth_pct is not None:
        if f.revenue_growth_pct >= 20:
            strengths.append(f"Strong top-line growth of {f.revenue_growth_pct:.0f}% suggests expanding demand."); score += 1
        elif f.revenue_growth_pct < 10:
            risks.append(f"Revenue growth of only {f.revenue_growth_pct:.0f}% is modest for a new listing."); score -= 0.5
    if f.pat_margin_pct is not None:
        if f.pat_margin_pct >= 10:
            strengths.append(f"Healthy PAT margin of {f.pat_margin_pct:.1f}% indicates pricing power."); score += 0.5
        elif f.pat_margin_pct < 5:
            risks.append(f"Thin PAT margin of {f.pat_margin_pct:.1f}% leaves little cushion."); score -= 0.5
    if f.debt_equity is not None:
        if f.debt_equity <= 0.5:
            strengths.append(f"Low leverage (debt/equity {f.debt_equity:.2f}) keeps the balance sheet flexible."); score += 0.5
        elif f.debt_equity >= 1.0:
            risks.append(f"High leverage (debt/equity {f.debt_equity:.2f}) is a debt burden risk."); score -= 1
    if f.pe is not None and f.industry_pe:
        if f.pe <= f.industry_pe:
            strengths.append(f"Valuation at {f.pe:.0f}x P/E is at or below the industry's {f.industry_pe:.0f}x."); score += 1
        elif f.pe > f.industry_pe * 1.25:
            risks.append(f"Valuation stretch: {f.pe:.0f}x P/E versus industry {f.industry_pe:.0f}x."); score -= 1
    if f.roe_pct is not None and f.roce_pct is not None and min(f.roe_pct, f.roce_pct) >= 15:
        strengths.append(f"Return ratios are strong (ROE {f.roe_pct:.0f}%, ROCE {f.roce_pct:.0f}%)."); score += 0.5
    if listing.ofs_cr and listing.issue_size_cr and listing.ofs_cr / listing.issue_size_cr > 0.5:
        risks.append(f"Mostly an offer for sale (Rs {listing.ofs_cr:g} cr of Rs {listing.issue_size_cr:g} cr): proceeds go to selling holders, not the business."); score -= 0.5
    elif listing.fresh_issue_cr and listing.issue_size_cr and listing.fresh_issue_cr / listing.issue_size_cr >= 0.6:
        strengths.append("Largely a fresh issue, so proceeds fund the company's growth."); score += 0.5
    if listing.gmp is not None and listing.gmp_pct is not None:
        if listing.gmp_pct >= 15:
            strengths.append(f"Grey market premium of {listing.gmp_pct:.0f}% signals strong listing demand (unofficial)."); score += 0.5
        elif listing.gmp_pct < 0:
            risks.append(f"Grey market discount of {listing.gmp_pct:.0f}% signals weak listing demand (unofficial)."); score -= 0.5
    if listing.subscription_times and listing.subscription_times >= 5:
        strengths.append(f"Issue subscribed {listing.subscription_times:.1f}x so far."); score += 0.5
    if f.notes:
        low = f.notes.lower()
        if any(w in low for w in ("customer", "concentration", "litigation", "dispute", "legal", "sebi")):
            risks.append(f"DRHP flag: {f.notes.strip()[:120]}"); score -= 0.5
        elif any(w in low for w in ("order book", "moat", "market leader", "patent", "anchor")):
            strengths.append(f"DRHP note: {f.notes.strip()[:120]}"); score += 0.5
    if news_score is not None:
        if news_score > 0.2:
            strengths.append(f"Recent news flow is net positive ({news_score:+.2f})."); score += 0.5
        elif news_score < -0.2:
            risks.append(f"Recent news flow is net negative ({news_score:+.2f})."); score -= 0.5

    if not strengths:
        strengths.append("No DRHP summary provided; add fundamentals in ipo_overrides.json for a fuller view.")
    if not risks:
        risks.append("Limited public information; new listings carry higher volatility than seasoned stocks.")
    sentiment = "Bullish" if score >= 2 else "Caution" if score <= -1 else "Neutral"
    return IPOAssessment(
        strengths=strengths[:3], risks=risks[:3], sentiment=sentiment,
        rationale=f"Rules-based read of the available metrics (score {score:+.1f}); set ANTHROPIC_API_KEY for an AI assessment.",
    )


def assess(listing: IPOListing, headlines: list[str], news_score: float | None = None) -> tuple[IPOAssessment, str]:
    if get_settings().llm_enabled:
        try:
            return llm_assess(listing, headlines), "llm"
        except Exception as exc:
            log.warning("IPO LLM assessment failed for %s, using rules: %s", listing.company, exc)
    return heuristic_assess(listing, headlines, news_score), "heuristic"
