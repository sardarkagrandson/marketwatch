"""Quantitative cutoff (barrier touch) probability under Geometric Brownian Motion.

    P(touch) ~= 2 * [1 - Phi( |ln(P_target / P_0)| / (sigma * sqrt(T)) )]

where sigma is annualized volatility and T is the horizon in years
(trading days / 252). This is the zero-drift reflection-principle result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

TRADING_DAYS_PER_YEAR = 252

ASSUMPTIONS = [
    "Prices follow Geometric Brownian Motion with zero drift (no expected up or down bias).",
    "Volatility is constant and equal to the trailing 1-year realised volatility of daily log returns.",
    "Horizon is counted in trading days (252 per year); gaps, circuit limits and events are ignored.",
    "This is a statistical estimate, not a forecast or a recommendation.",
]


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


@dataclass
class TouchProbability:
    current_price: float
    target_price: float
    horizon_days: int
    sigma_annual: float
    sigma_horizon: float
    distance_log: float
    distance_pct: float
    z_score: float
    touch_probability: float      # 0..1
    finish_beyond_probability: float  # 0..1, P(close beyond target at T)
    direction: str                # "above" | "below" | "at"
    assumptions: list[str]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["touch_probability_pct"] = round(self.touch_probability * 100.0, 2)
        d["finish_beyond_probability_pct"] = round(self.finish_beyond_probability * 100.0, 2)
        return d


def touch_probability(
    current_price: float,
    target_price: float,
    sigma_annual: float,
    horizon_days: int,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> TouchProbability:
    if current_price <= 0 or target_price <= 0:
        raise ValueError("Prices must be positive")
    if horizon_days <= 0:
        raise ValueError("Horizon must be at least 1 trading day")
    if sigma_annual <= 0:
        raise ValueError("Volatility must be positive")

    t_years = horizon_days / trading_days_per_year
    sigma_h = sigma_annual * math.sqrt(t_years)
    dist = math.log(target_price / current_price)
    direction = "above" if dist > 0 else "below" if dist < 0 else "at"

    z = abs(dist) / sigma_h
    p_touch = 2.0 * (1.0 - norm_cdf(z))
    p_finish = 1.0 - norm_cdf(z)
    if direction == "at":
        p_touch, p_finish = 1.0, 0.5

    return TouchProbability(
        current_price=current_price,
        target_price=target_price,
        horizon_days=horizon_days,
        sigma_annual=sigma_annual,
        sigma_horizon=sigma_h,
        distance_log=dist,
        distance_pct=(target_price / current_price - 1.0) * 100.0,
        z_score=z,
        touch_probability=min(max(p_touch, 0.0), 1.0),
        finish_beyond_probability=min(max(p_finish, 0.0), 1.0),
        direction=direction,
        assumptions=list(ASSUMPTIONS),
    )
