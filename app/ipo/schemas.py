"""Pydantic models for the IPO module."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class IPOFundamentals(BaseModel):
    revenue_growth_pct: float | None = None
    pat_margin_pct: float | None = None
    debt_equity: float | None = None
    pe: float | None = None
    industry_pe: float | None = None
    roe_pct: float | None = None
    roce_pct: float | None = None
    notes: str = ""

    def has_data(self) -> bool:
        return any(v is not None for k, v in self.model_dump().items() if k != "notes")


class IPOListing(BaseModel):
    key: str                      # stable id (symbol or slug)
    symbol: str | None = None
    company: str
    series: str = "EQ"            # EQ (mainboard) | SME
    open_date: date | None = None
    close_date: date | None = None
    price_low: float | None = None
    price_high: float | None = None
    lot_size: int | None = None
    issue_size_cr: float | None = None
    fresh_issue_cr: float | None = None
    ofs_cr: float | None = None
    subscription_times: float | None = None
    status: str = "upcoming"      # upcoming | open | closed
    gmp: float | None = None      # grey market premium in rupees (unofficial)
    gmp_source: str | None = None
    fundamentals: IPOFundamentals = Field(default_factory=IPOFundamentals)

    @property
    def est_listing_price(self) -> float | None:
        if self.price_high is None or self.gmp is None:
            return None
        return round(self.price_high + self.gmp, 2)

    @property
    def gmp_pct(self) -> float | None:
        if self.price_high and self.gmp is not None:
            return round(self.gmp / self.price_high * 100.0, 2)
        return None


class IPOAssessment(BaseModel):
    """Structured output for the catalyst & risk evaluator."""

    strengths: list[str] = Field(description="Exactly 3 core strengths (moats, ROE/ROCE, anchor book, growth).", min_length=1, max_length=5)
    risks: list[str] = Field(description="Exactly 3 key risks (valuation stretch, legal, concentration, debt).", min_length=1, max_length=5)
    sentiment: Literal["Bullish", "Neutral", "Caution"] = Field(description="Net pre-IPO sentiment.")
    rationale: str = Field(description="One or two sentences tying the verdict to the evidence.")


class ListedIPO(BaseModel):
    key: str
    symbol: str
    company: str
    series: str = "EQ"
    issue_price: float | None = None
    listing_date: date | None = None
    listing_open: float | None = None
    listing_close: float | None = None
    ltp: float | None = None
    listing_gain_pct: float | None = None
    total_gain_pct: float | None = None
    is_stale: bool = False
    error: str | None = None


class IPOCard(BaseModel):
    listing: IPOListing
    assessment: IPOAssessment | None = None
    assessment_method: str = "none"      # llm | heuristic | none
    news: list[dict] = Field(default_factory=list)
    news_score: float | None = None
