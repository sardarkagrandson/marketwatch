import math

import pytest

from app.market.probability import norm_cdf, touch_probability


def test_norm_cdf():
    assert abs(norm_cdf(0) - 0.5) < 1e-12
    assert abs(norm_cdf(1.96) - 0.975) < 1e-3


def test_touch_formula_matches_spec():
    p = touch_probability(100, 110, 0.30, 20)
    sigma_h = 0.30 * math.sqrt(20 / 252)
    z = abs(math.log(1.1)) / sigma_h
    assert abs(p.touch_probability - 2 * (1 - norm_cdf(z))) < 1e-12
    assert p.direction == "above"
    assert abs(p.distance_pct - 10.0) < 1e-9
    assert p.as_dict()["touch_probability_pct"] == round(p.touch_probability * 100, 2)


def test_touch_probability_monotonic():
    near = touch_probability(100, 102, 0.3, 20).touch_probability
    far = touch_probability(100, 120, 0.3, 20).touch_probability
    longer = touch_probability(100, 120, 0.3, 120).touch_probability
    assert near > far and longer > far
    assert touch_probability(100, 100, 0.3, 20).touch_probability == 1.0
    assert touch_probability(100, 80, 0.3, 20).direction == "below"


def test_validation():
    with pytest.raises(ValueError):
        touch_probability(0, 100, 0.3, 20)
    with pytest.raises(ValueError):
        touch_probability(100, 100, 0.3, 0)
    with pytest.raises(ValueError):
        touch_probability(100, 100, 0, 20)
