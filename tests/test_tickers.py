import pytest

from app.market.tickers import resolve_ticker


@pytest.mark.parametrize("query,symbol,method", [
    ("Tata Motors", "TATAMOTORS.NS", "alias"),
    ("TATAMOTORS.NS", "TATAMOTORS.NS", "exact-symbol"),
    ("tatamotors", "TATAMOTORS.NS", "exact-symbol"),
    ("RELIANCE.BO", "RELIANCE.BO", "exact-symbol"),
    ("HDFC Bank Ltd", "HDFCBANK.NS", "alias"),
    ("L&T", "LT.NS", "alias"),
    ("maruti suzuki share", "MARUTI.NS", "fuzzy"),
    ("infosys limited", "INFY.NS", "alias"),
])
def test_resolution(query, symbol, method):
    r = resolve_ticker(query, allow_search=False)
    assert r.symbol == symbol
    assert r.method == method
    assert r.confidence >= 0.75


def test_fallback_and_exchange():
    r = resolve_ticker("ZZZUNKNOWN", allow_search=False)
    assert r.symbol == "ZZZUNKNOWN.NS" and r.method == "fallback" and r.confidence < 0.5
    assert resolve_ticker("TCS.BO", allow_search=False).exchange == "BSE"
    with pytest.raises(ValueError):
        resolve_ticker("   ")
