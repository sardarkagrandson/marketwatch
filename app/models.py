"""ORM models."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SpotlightEntry(Base):
    __tablename__ = "spotlight"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    cutoff_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # "above" = sell/breakout trigger, "below" = buy/dip trigger
    cutoff_direction: Mapped[str] = mapped_column(String(8), default="above")
    email: Mapped[str] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_news_alert_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def job_id(self) -> str:
        return f"spotlight-{self.id}"


class AlertLog(Base):
    __tablename__ = "alert_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spotlight_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # price | news
    subject: Mapped[str] = mapped_column(String(256))
    recipient: Mapped[str] = mapped_column(String(256))
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    buy_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    buy_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsCache(Base):
    """Raw RSS fetch cache keyed by symbol (prevents feed throttling)."""

    __tablename__ = "news_cache"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[str] = mapped_column(Text)  # JSON list of articles


class NewsAssessmentCache(Base):
    """Per-article sentiment results so LLM calls are never repeated."""

    __tablename__ = "news_assessments"

    article_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON NewsAssessment
    source: Mapped[str] = mapped_column(String(16), default="heuristic")  # llm | heuristic
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
