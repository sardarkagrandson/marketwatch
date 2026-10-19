"""HTML email alerts via aiosmtplib; falls back to writing .html files to data/outbox."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings

log = logging.getLogger(__name__)

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=select_autoescape(["html"]))


def render_alert(context: dict) -> str:
    return _env.get_template("email/alert.html").render(**context)


def _outbox_path(subject: str) -> Path:
    outbox = get_settings().resolved_data_dir / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:60]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return outbox / f"{stamp}-{slug}.html"


async def send_html_email(to: str, subject: str, html: str) -> tuple[bool, str]:
    """Return (delivered, detail). Without SMTP config the mail is saved to the outbox."""
    settings = get_settings()
    if not settings.smtp_enabled:
        path = _outbox_path(subject)
        path.write_text(html, encoding="utf-8")
        log.info("SMTP not configured; alert written to %s", path)
        return False, f"SMTP not configured; saved to {path}"

    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("This alert requires an HTML-capable mail client.")
    msg.add_alternative(html, subtype="html")
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_use_tls,
            timeout=30,
        )
        return True, "delivered"
    except Exception as exc:
        log.error("email delivery failed: %s", exc)
        return False, f"delivery failed: {exc}"
