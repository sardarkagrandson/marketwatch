"""Resolve company names / symbols to Yahoo Finance tickers (.NS / .BO)."""
from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_SYMBOLS_PATH = Path(__file__).with_name("nse_symbols.json")
_SUFFIXES = (".NS", ".BO")


@dataclass
class ResolvedTicker:
    query: str
    symbol: str          # e.g. TATAMOTORS.NS
    base_symbol: str     # e.g. TATAMOTORS
    name: str
    exchange: str        # NSE | BSE
    confidence: float    # 0..1
    method: str          # exact-symbol | alias | fuzzy | suffix | search | fallback

    def as_dict(self) -> dict:
        return asdict(self)


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\b(ltd|limited|pvt|private|inc|corp|corporation|co|company|india)\b\.?", " ", s)
    s = re.sub(r"[^a-z0-9&]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache
def _load_symbols() -> list[dict]:
    with _SYMBOLS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache
def _index() -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (by_symbol, by_normalized_name_or_alias)."""
    by_symbol: dict[str, dict] = {}
    by_text: dict[str, dict] = {}
    for row in _load_symbols():
        by_symbol[row["symbol"].upper()] = row
        by_text[_norm(row["name"])] = row
        for alias in row.get("aliases", []):
            by_text[_norm(alias)] = row
    return by_symbol, by_text


def known_symbols() -> list[dict]:
    return list(_load_symbols())


def resolve_ticker(query: str, allow_search: bool = True) -> ResolvedTicker:
    """Resolve free-form text to a ticker. Never raises for non-empty input."""
    q = (query or "").strip()
    if not q:
        raise ValueError("Empty query")
    by_symbol, by_text = _index()

    # 1. Already a Yahoo-style ticker with suffix
    upper = q.upper()
    if upper.endswith(_SUFFIXES):
        base = upper[:-3]
        row = by_symbol.get(base)
        return ResolvedTicker(
            query=q,
            symbol=upper,
            base_symbol=base,
            name=row["name"] if row else base,
            exchange="NSE" if upper.endswith(".NS") else "BSE",
            confidence=1.0,
            method="exact-symbol",
        )

    # 2. Bare NSE symbol
    if upper in by_symbol:
        row = by_symbol[upper]
        return ResolvedTicker(q, f"{upper}.NS", upper, row["name"], "NSE", 1.0, "exact-symbol")

    # 3. Exact name / alias match
    nq = _norm(q)
    if nq in by_text:
        row = by_text[nq]
        return ResolvedTicker(q, f"{row['symbol']}.NS", row["symbol"], row["name"], "NSE", 0.98, "alias")

    # 4. Fuzzy name / alias match
    candidates = list(by_text.keys())
    matches = difflib.get_close_matches(nq, candidates, n=1, cutoff=0.72)
    if not matches:
        # token containment, e.g. "tata motors share" -> "tata motors"
        for text, row in by_text.items():
            if text and (text in nq or nq in text) and len(text) >= 4:
                matches = [text]
                break
    if matches:
        row = by_text[matches[0]]
        score = difflib.SequenceMatcher(None, nq, matches[0]).ratio()
        return ResolvedTicker(
            q, f"{row['symbol']}.NS", row["symbol"], row["name"], "NSE", round(max(score, 0.75), 2), "fuzzy"
        )

    # 5. Yahoo search (network) - best effort
    if allow_search:
        hit = _yahoo_search(q)
        if hit:
            return hit

    # 6. Fallback: treat as NSE symbol
    base = re.sub(r"[^A-Z0-9&-]", "", upper)
    return ResolvedTicker(q, f"{base}.NS", base, base, "NSE", 0.3, "fallback")


def _yahoo_search(query: str) -> ResolvedTicker | None:
    try:
        import yfinance as yf

        res = yf.Search(query, max_results=8, news_count=0)
        quotes = getattr(res, "quotes", None) or []
    except Exception as exc:  # network errors, API changes
        log.debug("yfinance search failed for %r: %s", query, exc)
        return None
    for item in quotes:
        sym = str(item.get("symbol", "")).upper()
        if sym.endswith(_SUFFIXES):
            base = sym[:-3]
            return ResolvedTicker(
                query=query,
                symbol=sym,
                base_symbol=base,
                name=item.get("longname") or item.get("shortname") or base,
                exchange="NSE" if sym.endswith(".NS") else "BSE",
                confidence=0.85,
                method="search",
            )
    return None


def suggest(query: str, limit: int = 8) -> list[dict]:
    """Rank bundled symbols for type-ahead: symbol prefix > name/alias prefix > substring > fuzzy."""
    q = (query or "").strip()
    if not q:
        return []
    nq = _norm(q)
    uq = q.upper().replace(".NS", "").replace(".BO", "")
    scored: dict[str, tuple[float, dict]] = {}

    def consider(row: dict, score: float) -> None:
        cur = scored.get(row["symbol"])
        if cur is None or score > cur[0]:
            scored[row["symbol"]] = (score, row)

    for idx, row in enumerate(_load_symbols()):
        sym = row["symbol"]
        texts = [row["name"], *row.get("aliases", [])]
        row = {**row, "_rank": idx}
        if sym == uq:
            consider(row, 100)
        elif sym.startswith(uq):
            consider(row, 90 - len(sym) * 0.1)
        for t in texts:
            nt = _norm(t)
            if not nt:
                continue
            if nt == nq:
                consider(row, 95)
            elif nt.startswith(nq):
                consider(row, 80 - len(nt) * 0.1)
            elif any(w.startswith(nq) for w in nt.split()):
                consider(row, 70)
            elif nq in nt:
                consider(row, 60)
            elif len(nq) >= 4:
                r = difflib.SequenceMatcher(None, nq, nt).ratio()
                if r >= 0.6:
                    consider(row, 40 * r)
    # Tie-break by list order (roughly market-cap order), so TATAMOTORS beats TATACHEM for "tata".
    ranked = sorted(scored.values(), key=lambda x: (-x[0], x[1]["_rank"]))[:limit]
    return [
        {"symbol": f"{row['symbol']}.NS", "base_symbol": row["symbol"], "name": row["name"], "exchange": "NSE"}
        for _, row in ranked
    ]
