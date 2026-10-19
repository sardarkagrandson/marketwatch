# MarketWatch - Indian Stock Market Sentiment & Technical Intelligence

A FastAPI application for NSE / BSE equities that combines live market data,
technical indicators, a structured news-sentiment matrix, a statistical cutoff
probability calculator, an automated Spotlight watchlist with email alerts, and
a portfolio health dashboard. The UI follows a Groww-inspired fintech design
with a toggleable dark mode.

> Signals are labelled as *Bullish / Bearish Bias* and *Technical Setups*.
> Nothing here is investment advice. Equity investments are subject to market
> risk; consult a SEBI-registered advisor before trading.

## Features

| Module | What it does |
|---|---|
| Ticker resolution | Accepts names or symbols (`Tata Motors`, `TATAMOTORS.NS`, `RELIANCE.BO`). Bundled map of ~175 NSE companies with aliases + fuzzy matching, Yahoo search fallback. |
| Market data engine | LTP, previous close, day range, 52-week range, volume via `yfinance`. Flags prices as previous-session closes outside 09:15-15:30 IST. In-memory TTL cache. |
| Technicals | 14-day RSI (Wilder), 20/50/200 EMA, 20-day ATR (Wilder), annualised volatility, plus labelled setups / breakdowns. Computed natively with pandas. |
| News & sentiment matrix | Google News RSS + Yahoo Finance RSS for the past 7 days, deduplicated, cached in SQLite. Each article is classified (category, sentiment, impact -1..+1, reasoning) by Claude via structured output (Pydantic), with a keyword heuristic fallback when no API key is set. Aggregated into a recency-weighted score and momentum bias. |
| Cutoff probability | `P(touch) = 2 * [1 - Phi(|ln(P_target/P_0)| / (sigma * sqrt(T)))]` using 1-year realised volatility, with the assumptions stated on screen. |
| Spotlight watchlist | APScheduler (SQLite job store) polls each ticker on its own interval during market hours. HTML email alerts (aiosmtplib) when a cutoff is hit or a news item scores beyond +/-0.7, with news context and a technical summary. |
| Portfolio health | Holdings with buy price / quantity / date. Net P&L, day change, value-weighted sentiment exposure, and flags for negative catalysts, RSI extremes and 200 EMA breaks. |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit as needed
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

### Demo without network

```bash
OFFLINE_MODE=true uvicorn app.main:app --reload
```

Offline mode serves deterministic synthetic prices and sample headlines so every
screen works without Yahoo Finance or RSS access. The heuristic sentiment
classifier is used, and alert emails are written to `data/outbox/*.html`.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `OFFLINE_MODE` | `true` for synthetic data (no network). |
| `ANTHROPIC_API_KEY` | Enables LLM sentiment classification. Model via `SENTIMENT_MODEL` (default `claude-opus-5-5`). Server-side refusal fallbacks are enabled by default. |
| `SMTP_HOST/PORT/USERNAME/PASSWORD/USE_TLS/FROM` | Email delivery. When `SMTP_HOST` is empty, alerts are saved to `data/outbox/`. |
| `MARKET_HOLIDAYS` | Comma-separated `YYYY-MM-DD` dates on which polling is skipped. |
| `QUOTE_CACHE_SECONDS`, `HISTORY_CACHE_SECONDS`, `NEWS_CACHE_SECONDS` | Cache TTLs (defaults 60 / 900 / 1800). |
| `DATA_DIR` | Location of `marketwatch.db` (app data) and `jobs.db` (scheduler). |

## JSON API

| Method & path | Description |
|---|---|
| `GET /api/resolve?q=` | Resolve a name/symbol to a ticker. |
| `GET /api/stock/{query}` | Full analysis: quote, technicals, sentiment summary, news matrix, sparkline. |
| `POST /api/probability` | `{query, target_price, horizon_days}` -> touch probability and assumptions. |
| `GET/POST /api/spotlight`, `PATCH/DELETE /api/spotlight/{id}`, `POST /api/spotlight/{id}/poll` | Watchlist CRUD and on-demand poll. |
| `GET /api/alerts` | Alert delivery log. |
| `GET/POST /api/portfolio`, `DELETE /api/portfolio/{id}` | Holdings and portfolio health. |
| `GET /api/health` | Service status, market state, scheduler state. |

## Project layout

```
app/
  main.py            FastAPI routes (HTML + JSON)
  config.py          pydantic-settings
  db.py, models.py   SQLAlchemy + SQLite
  services.py        analysis aggregator
  market/            tickers.py, data.py (providers, cache, market hours), indicators.py, probability.py
  news/              ingest.py (RSS, dedupe, cache), sentiment.py (LLM + heuristic), schemas.py
  alerts/            scheduler.py (APScheduler), email.py (aiosmtplib + HTML template)
  portfolio/         health.py
  templates/, static/   Jinja2 UI (Tailwind CDN, Inter / JetBrains Mono, dark mode)
tests/               pytest suite (runs fully offline)
```

## Tests

```bash
pytest -q
```

The suite uses offline data and a temporary SQLite database; no network or API
keys are required.

## Notes and limitations

- Market data is delayed (Yahoo Finance). NSE holidays are not bundled; set
  `MARKET_HOLIDAYS` to skip polling on those days.
- The `ta` library is listed as optional: the same RSI / EMA / ATR definitions are
  implemented in `app/market/indicators.py` so the app runs on Python 3.13 where
  `ta` currently fails to build.
- The UI loads Tailwind and Google Fonts from CDNs; `app/static/app.css` carries
  the core design tokens so pages remain usable if those are blocked.
