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


class SMTPStageError(Exception):
    """Delivery failure with a plain-language explanation of which stage failed."""


async def _open_ipv4_socket(host: str, port: int, timeout: float):
    """Connect over IPv4 explicitly. Docker containers often have an IPv6 address but no
    IPv6 route, and asyncio may then sit on the AAAA record until the timeout."""
    import asyncio
    import socket

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SMTPStageError(f"DNS lookup for {host} failed inside the container ({exc}). Check the container's internet access.")
    if not infos:
        raise SMTPStageError(f"{host} has no IPv4 address")
    last = None
    for family, socktype, proto, _, addr in infos:
        sock = socket.socket(family, socktype, proto)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(loop.sock_connect(sock, addr), timeout)
            return sock, addr[0]
        except (asyncio.TimeoutError, OSError) as exc:
            sock.close()
            last = exc
    if isinstance(last, asyncio.TimeoutError):
        raise SMTPStageError(f"TCP connection to {host}:{port} timed out: this network or ISP is blocking port {port}. "
                             f"Try SMTP_PORT=465, or a provider that offers port 2525 (e.g. Brevo).")
    raise SMTPStageError(f"TCP connection to {host}:{port} refused ({last}).")


async def send_html_email(to: str, subject: str, html: str) -> tuple[bool, str]:
    """Return (delivered, detail). Without SMTP config the mail is saved to the outbox."""
    settings = get_settings()
    if not settings.smtp_enabled:
        path = _outbox_path(subject)
        path.write_text(html, encoding="utf-8")
        log.info("SMTP not configured; alert written to %s", path)
        return False, f"SMTP not configured; saved to {path}"

    import asyncio

    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("This alert requires an HTML-capable mail client.")
    msg.add_alternative(html, subtype="html")

    host, port = settings.smtp_host.strip(), settings.smtp_port
    implicit_tls = port == 465          # SMTPS: TLS from the first byte
    timeout = settings.smtp_timeout_seconds
    try:
        sock, ip = await _open_ipv4_socket(host, port, timeout) if settings.smtp_prefer_ipv4 else (None, None)
        client = aiosmtplib.SMTP(
            hostname=host, port=port, timeout=timeout, sock=sock,
            use_tls=implicit_tls, start_tls=(settings.smtp_use_tls and not implicit_tls),
        )
        try:
            await client.connect()
        except aiosmtplib.SMTPConnectTimeoutError as exc:
            raise SMTPStageError(
                f"Connected to {host}:{port}{f' ({ip})' if ip else ''} but the server never sent its greeting ({exc}). "
                f"A firewall or transparent proxy is filtering SMTP on this network. Try SMTP_PORT=465, or port 2525 with a provider like Brevo."
            )
        try:
            if settings.smtp_username:
                await client.login(settings.smtp_username, settings.smtp_password)
            await client.send_message(msg)
        finally:
            try:
                await client.quit()
            except Exception:
                client.close()
        return True, "delivered"
    except SMTPStageError as exc:
        log.error("email delivery failed: %s", exc)
        return False, f"delivery failed: {exc}"
    except aiosmtplib.SMTPAuthenticationError as exc:
        log.error("email auth failed: %s", exc)
        return False, ("delivery failed: the mail server rejected the username/password. For Gmail this must be a 16-character "
                       "App Password (2-Step Verification on), not the account password.")
    except (aiosmtplib.SMTPException, asyncio.TimeoutError, OSError) as exc:
        log.error("email delivery failed: %s", exc)
        return False, f"delivery failed: {exc}"


async def send_test_email(to: str) -> tuple[bool, str]:
    """Send a short test message so SMTP settings can be verified end to end."""
    html = _env.get_template("email/test.html").render(to=to, generated_at=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"))
    return await send_html_email(to, "[SnitchofDalal] Test email - alerts are working", html)
