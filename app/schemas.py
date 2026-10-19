"""Request / response models for the JSON API."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class ProbabilityRequest(BaseModel):
    query: str = Field(min_length=1, description="Company name or ticker")
    target_price: float = Field(gt=0)
    horizon_days: int = Field(ge=1, le=750, description="Trading days")


class SpotlightCreate(BaseModel):
    query: str = Field(min_length=1)
    poll_interval_minutes: int = Field(default=60, ge=1, le=1440)
    cutoff_price: float | None = Field(default=None, gt=0)
    cutoff_direction: Literal["above", "below"] = "above"
    email: EmailStr
    enabled: bool = True


class SpotlightUpdate(BaseModel):
    poll_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    cutoff_price: float | None = Field(default=None, gt=0)
    cutoff_direction: Literal["above", "below"] | None = None
    email: EmailStr | None = None
    enabled: bool | None = None


class HoldingCreate(BaseModel):
    query: str = Field(min_length=1)
    buy_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    buy_date: date

    @field_validator("buy_date")
    @classmethod
    def not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("buy_date cannot be in the future")
        return v
