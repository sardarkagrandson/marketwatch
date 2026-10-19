"""APScheduler-driven Spotlight poller with a SQLite job store."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.alerts.email import render_alert, send_html_email
from app.config import get_settings
from app.db import session_scope
from app.market.data import is_market_open, market_status
from app.models import AlertLog, SpotlightEntry
from app.news.sentiment import HIGH_IMPACT_THRESHOLD

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
PRICE_ALERT_COOLDOWN_MINUTES = 240


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=get_settings().jobstore_url)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
            timezone="Asia/Kolkata",
        )
    return _scheduler


def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
    sync_jobs()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def schedule_entry(entry: SpotlightEntry) -> None:
    sched = get_scheduler()
    if not entry.enabled:
        remove_job(entry.id)
        return
    sched.add_job(
        poll_spotlight,
        trigger=IntervalTrigger(minutes=max(1, entry.poll_interval_minutes)),
        id=entry.job_id,
        args=[entry.id],
        replace_existing=True,
        name=f"Spotlight {entry.symbol}",
        # First poll shortly after (re)scheduling so the table fills in quickly.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=15),
    )


def remove_job(entry_id: int) -> None:
    try:
        get_scheduler().remove_job(f"spotlight-{entry_id}")
    except Exception:
        pass


def sync_jobs() -> None:
    """Make scheduler jobs match the Spotlight table (called at startup)."""
    sched = get_scheduler()
    with session_scope() as s:
        entries = s.query(SpotlightEntry).all()
        wanted = {e.job_id for e in entries if e.enabled}
        for job in sched.get_jobs():
            if job.id.startswith("spotlight-") and job.id not in wanted:
                sched.remove_job(job.id)
        for e in entries:
            schedule_entry(e)


def next_run_times() -> dict[str, datetime | None]:
    try:
        return {j.id: j.next_run_time for j in get_scheduler().get_jobs()}
    except Exception:
        return {}


# ---------------------------------------------------------------- evaluation
def price_triggered(entry: SpotlightEntry, ltp: float, day_high: float | None = None, day_low: float | None = None) -> bool:
    """True when the cutoff was reached. During a session the day's high/low are checked too,
    so a touch that happened between two polls is still caught."""
    if entry.cutoff_price is None:
        return False
    if entry.cutoff_direction == "below":
        lowest = min(ltp, day_low) if day_low is not None else ltp
        return lowest <= entry.cutoff_price
    highest = max(ltp, day_high) if day_high is not None else ltp
    return highest >= entry.cutoff_price


def news_catalyst(analysis) -> tuple[str | None, list[dict]]:
    """Return (key, rows) for high-impact items not yet alerted; key is None when nothing qualifies."""
    rows = [r for r in analysis.matrix if abs(r["impact_score"]) > HIGH_IMPACT_THRESHOLD]
    if not rows:
        return None, []
    key = ",".join(sorted(r["id"] for r in rows))[:64]
    return key, rows


async def poll_spotlight(entry_id: int, force: bool = False) -> dict:
    """Job body: fetch latest data, evaluate triggers and send alerts."""
    from app.services import analyze

    with session_scope() as s:
        entry = s.get(SpotlightEntry, entry_id)
        if entry is None:
            remove_job(entry_id)
            return {"status": "missing"}
        if not entry.enabled:
            return {"status": "disabled"}
        symbol, email = entry.symbol, entry.email

    if not force and not is_market_open():
        return {"status": "market-closed"}

    try:
        analysis = await asyncio.to_thread(analyze, symbol)
    except Exception as exc:
        log.warning("poll failed for %s: %s", symbol, exc)
        with session_scope() as s:
            entry = s.get(SpotlightEntry, entry_id)
            if entry:
                entry.last_error = str(exc)[:500]
                entry.last_polled_at = datetime.now(timezone.utc)
        return {"status": "error", "detail": str(exc)}

    now = datetime.now(timezone.utc)
    sent: list[str] = []
    with session_scope() as s:
        entry = s.get(SpotlightEntry, entry_id)
        entry.last_polled_at = now
        entry.last_price = analysis.quote.ltp
        entry.last_sentiment = analysis.sentiment.score
        entry.last_error = None

        triggers: list[tuple[str, str, dict]] = []
        q = analysis.quote
        intraday = q.market_open and not q.is_stale
        if price_triggered(entry, q.ltp, q.day_high if intraday else None, q.day_low if intraday else None):
            last = entry.last_price_alert_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last is None or (now - last).total_seconds() > PRICE_ALERT_COOLDOWN_MINUTES * 60:
                verb = "reached or crossed above" if entry.cutoff_direction == "above" else "fell to or below"
                triggers.append((
                    "price",
                    f"{entry.symbol} {verb} your cutoff of Rs {entry.cutoff_price:,.2f}",
                    {"cutoff_price": entry.cutoff_price, "cutoff_direction": entry.cutoff_direction},
                ))
                entry.last_price_alert_at = now

        key, rows = news_catalyst(analysis)
        if key and key != entry.last_news_alert_key:
            strongest = max(rows, key=lambda r: abs(r["impact_score"]))
            triggers.append((
                "news",
                f"{entry.symbol}: high-impact {strongest['sentiment'].lower()} news catalyst ({strongest['impact_score']:+.2f})",
                {"catalysts": rows},
            ))
            entry.last_news_alert_key = key

        spotlight_id = entry.id
        entry_data = {
            "symbol": entry.symbol, "name": entry.name or analysis.ticker.name,
            "cutoff_price": entry.cutoff_price, "cutoff_direction": entry.cutoff_direction,
        }

    for kind, subject, extra in triggers:
        html = render_alert({
            "kind": kind, "subject": subject, "entry": entry_data, "quote": analysis.quote.as_dict(),
            "technicals": analysis.technicals.as_dict(), "sentiment": analysis.sentiment.model_dump(),
            "matrix": analysis.matrix[:8], "market": market_status(), "extra": extra,
            "generated_at": now.strftime("%d %b %Y %H:%M UTC"),
        })
        delivered, detail = await send_html_email(email, f"[SnitchofDalal] {subject}", html)
        with session_scope() as s:
            s.add(AlertLog(spotlight_id=spotlight_id, symbol=symbol, kind=kind, subject=subject,
                           recipient=email, delivered=delivered, detail=detail))
        sent.append(kind)

    return {"status": "ok", "ltp": analysis.quote.ltp, "alerts": sent}
