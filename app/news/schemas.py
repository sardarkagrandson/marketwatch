"""Pydantic models for news articles and the sentiment matrix."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["Earnings", "Regulatory/Legal", "Product/Expansion", "Macro/Sector", "Management", "Other"]
Sentiment = Literal["Bullish", "Bearish", "Neutral"]


class NewsArticle(BaseModel):
    id: str
    headline: str
    source: str = ""
    published_at: datetime
    link: str
    summary: str = ""

    @property
    def age_days(self) -> float:
        from datetime import timezone

        now = datetime.now(timezone.utc)
        pub = self.published_at if self.published_at.tzinfo else self.published_at.replace(tzinfo=timezone.utc)
        return max((now - pub).total_seconds() / 86400.0, 0.0)


class NewsAssessment(BaseModel):
    """One row of the sentiment matrix."""

    article_id: str = Field(description="Identifier of the article being assessed (copy exactly).")
    category: Category = Field(description="Primary category of the news item.")
    sentiment: Sentiment = Field(description="Likely effect on the stock's price.")
    impact_score: float = Field(
        ge=-1.0, le=1.0,
        description="Expected price impact from -1.0 (strongly bearish) to +1.0 (strongly bullish). 0 for noise.",
    )
    reasoning: str = Field(description="One-sentence rationale citing the key fact from the headline.")


class NewsMatrix(BaseModel):
    """Structured output returned by the LLM for a batch of articles."""

    assessments: list[NewsAssessment]


class SentimentSummary(BaseModel):
    score: float                      # -1..1 recency-weighted mean impact
    momentum_bias: Literal["Bullish Bias", "Bearish Bias", "Neutral"]
    recent_score: float               # last 3 days
    article_count: int
    bullish: int
    bearish: int
    neutral: int
    high_impact: list[str]            # article ids with |impact| > 0.7
    method: Literal["llm", "heuristic", "mixed", "none"]
    categories: dict[str, int]
