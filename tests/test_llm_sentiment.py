"""Verify the structured-output LLM path without network, via a stubbed Anthropic client."""
from datetime import datetime, timezone
from types import SimpleNamespace

import anthropic
import pytest

from app.config import get_settings
from app.news.ingest import article_id
from app.news.schemas import NewsArticle, NewsAssessment, NewsMatrix
from app.news import sentiment as sent


def _art(h, link):
    return NewsArticle(id=article_id(h, link), headline=h, source="T", published_at=datetime.now(timezone.utc), link=link)


class _Parse:
    def __init__(self, recorder, result):
        self.recorder, self.result = recorder, result

    def parse(self, **kwargs):
        self.recorder.update(kwargs)
        return self.result


def _client_factory(recorder, result):
    def factory(**kwargs):
        return SimpleNamespace(beta=SimpleNamespace(messages=_Parse(recorder, result)))
    return factory


def test_llm_assess_builds_request_and_filters_ids(monkeypatch):
    arts = [_art("Co beats estimates", "https://x/1"), _art("Co fined by SEBI", "https://x/2")]
    matrix = NewsMatrix(assessments=[
        NewsAssessment(article_id=arts[0].id, category="Earnings", sentiment="Bullish", impact_score=0.6, reasoning="beat"),
        NewsAssessment(article_id=arts[1].id, category="Regulatory/Legal", sentiment="Bearish", impact_score=-0.8, reasoning="fine"),
        NewsAssessment(article_id="not-an-article", category="Other", sentiment="Neutral", impact_score=0.0, reasoning="x"),
    ])
    recorded = {}
    result = SimpleNamespace(stop_reason="end_turn", parsed_output=matrix)
    monkeypatch.setattr(anthropic, "Anthropic", _client_factory(recorded, result))

    out = sent.llm_assess(arts, "Co", "CO.NS")
    assert [a.article_id for a in out] == [arts[0].id, arts[1].id]
    assert recorded["output_format"] is NewsMatrix
    assert recorded["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in recorded["betas"]
    assert recorded["model"] == get_settings().sentiment_model
    assert arts[0].id in recorded["messages"][0]["content"]


def test_llm_refusal_raises(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", _client_factory({}, SimpleNamespace(stop_reason="refusal", parsed_output=None)))
    with pytest.raises(RuntimeError):
        sent.llm_assess([_art("h", "https://x/9")], "Co", "CO.NS")


def test_assess_articles_uses_llm_then_caches(monkeypatch, db):
    arts = [_art("Cached Co wins big order", "https://x/c1")]
    matrix = NewsMatrix(assessments=[NewsAssessment(article_id=arts[0].id, category="Product/Expansion",
                                                    sentiment="Bullish", impact_score=0.5, reasoning="order")])
    calls = {"n": 0}

    def fake_llm(pending, name, symbol):
        calls["n"] += 1
        return matrix.assessments

    monkeypatch.setattr(sent, "llm_assess", fake_llm)
    monkeypatch.setattr(type(get_settings()), "llm_enabled", property(lambda self: True))
    res, method = sent.assess_articles(arts, "Cached Co", "CACHED.NS")
    assert method == "llm" and res[arts[0].id].impact_score == 0.5
    res2, method2 = sent.assess_articles(arts, "Cached Co", "CACHED.NS")
    assert method2 == "llm" and calls["n"] == 1  # second call served from SQLite cache


def test_assess_articles_falls_back_to_heuristic(monkeypatch, db):
    arts = [_art("Fallback Co profit jumps 30%", "https://x/f1")]

    def boom(*a, **k):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(sent, "llm_assess", boom)
    monkeypatch.setattr(type(get_settings()), "llm_enabled", property(lambda self: True))
    res, method = sent.assess_articles(arts, "Fallback Co", "FALLBACK.NS")
    assert method == "heuristic" and res[arts[0].id].sentiment == "Bullish"
