"""Device licensing: offline-verifiable Ed25519 licence tokens bound to a device ID.

Flow
----
1. The operator runs `python tools/license_admin.py keygen` once. The private key stays
   with the operator; the public key goes into LICENSE_PUBLIC_KEY (in .env / the image).
2. On first run each installation generates a random Device ID (stored in the data volume)
   and shows it on the activation screen.
3. The operator issues a token for that Device ID with
   `python tools/license_admin.py issue --device-id ... --name ... --days 365`.
4. The user pastes the token; the app verifies the signature, device match and expiry,
   and stores it. Every request is then gated by the middleware in app.main.

When LICENSE_PUBLIC_KEY is empty, licensing is disabled (open access).
"""
from __future__ import annotations

import base64
import json
import secrets
import threading
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.config import get_settings

TOKEN_PREFIX = "SOD1."
DEVICE_FILE = "device.json"


class LicenseError(Exception):
    pass


# ---------------------------------------------------------------- encoding helpers
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------------------------------------------------------- keys
def generate_keypair() -> tuple[str, str]:
    """Return (private_pem, public_key_b64)."""
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pem, _b64e(pub)


def load_private_key(pem: str | bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem.encode() if isinstance(pem, str) else pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise LicenseError("Private key is not an Ed25519 key")
    return key


def load_public_key(b64: str) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(_b64d(b64.strip()))
    except Exception as exc:
        raise LicenseError(f"Invalid LICENSE_PUBLIC_KEY: {exc}") from exc


# ---------------------------------------------------------------- device id
def _device_file() -> Path:
    return get_settings().resolved_data_dir / DEVICE_FILE


def get_or_create_device_id() -> str:
    path = _device_file()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if data.get("device_id"):
                return data["device_id"]
        except Exception:
            pass
    raw = secrets.token_hex(8).upper()
    device_id = "-".join(raw[i:i + 4] for i in range(0, 16, 4))
    path.write_text(json.dumps({"device_id": device_id, "created_at": datetime.now(timezone.utc).isoformat()}))
    return device_id


# ---------------------------------------------------------------- tokens
@dataclass
class LicenseInfo:
    device_id: str
    name: str
    issued: str
    expires: str | None
    plan: str = "standard"

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def expired(self) -> bool:
        return bool(self.expires) and date.fromisoformat(self.expires) < date.today()


def issue_token(private_pem: str, device_id: str, name: str, days: int | None = 365, plan: str = "standard") -> str:
    key = load_private_key(private_pem)
    today = date.today()
    payload = {
        "v": 1,
        "device_id": device_id.strip().upper(),
        "name": name.strip(),
        "issued": today.isoformat(),
        "expires": (today + timedelta(days=days)).isoformat() if days else None,
        "plan": plan,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = key.sign(body)
    return f"{TOKEN_PREFIX}{_b64e(body)}.{_b64e(sig)}"


def decode_token(token: str) -> tuple[dict, bytes, bytes]:
    token = (token or "").strip()
    if not token.startswith(TOKEN_PREFIX):
        raise LicenseError("This does not look like a SnitchofDalal licence key")
    try:
        body_b64, sig_b64 = token[len(TOKEN_PREFIX):].split(".", 1)
        body = _b64d(body_b64)
        payload = json.loads(body)
        return payload, body, _b64d(sig_b64)
    except Exception as exc:
        raise LicenseError("Licence key is malformed") from exc


def verify_token(token: str, public_key_b64: str, device_id: str | None = None, today: date | None = None) -> LicenseInfo:
    payload, body, sig = decode_token(token)
    try:
        load_public_key(public_key_b64).verify(sig, body)
    except InvalidSignature:
        raise LicenseError("Licence signature is invalid (not issued for this build)")
    if payload.get("v") != 1:
        raise LicenseError("Unsupported licence version")
    info = LicenseInfo(
        device_id=str(payload.get("device_id", "")).upper(),
        name=str(payload.get("name", "")),
        issued=str(payload.get("issued", "")),
        expires=payload.get("expires"),
        plan=str(payload.get("plan", "standard")),
    )
    if device_id and info.device_id != device_id.strip().upper():
        raise LicenseError(f"Licence was issued for device {info.device_id}, but this device is {device_id}")
    if info.expires:
        if date.fromisoformat(info.expires) < (today or date.today()):
            raise LicenseError(f"Licence expired on {info.expires}")
    return info


# ---------------------------------------------------------------- app state
_lock = threading.Lock()
_cache: dict = {"checked_at": 0.0, "status": None}
CACHE_SECONDS = 60


def licensing_required() -> bool:
    return bool(get_settings().license_public_key.strip())


def _stored_token():
    from app.db import session_scope
    from app.models import DeviceLicense

    with session_scope() as s:
        row = s.query(DeviceLicense).order_by(DeviceLicense.id.desc()).first()
        return row.token if row else None


def license_status(force: bool = False) -> dict:
    """Return {required, active, device_id, name, expires, error}."""
    now = time.monotonic()
    with _lock:
        if not force and _cache["status"] is not None and now - _cache["checked_at"] < CACHE_SECONDS:
            return _cache["status"]
    device_id = get_or_create_device_id()
    status = {"required": licensing_required(), "active": True, "device_id": device_id,
              "name": None, "expires": None, "error": None}
    if status["required"]:
        token = _stored_token()
        if not token:
            status.update(active=False, error="This device has not been activated yet.")
        else:
            try:
                info = verify_token(token, get_settings().license_public_key, device_id)
                status.update(name=info.name, expires=info.expires)
            except LicenseError as exc:
                status.update(active=False, error=str(exc))
    with _lock:
        _cache.update(checked_at=now, status=status)
    return status


def activate(token: str) -> dict:
    from app.db import session_scope
    from app.models import DeviceLicense

    device_id = get_or_create_device_id()
    info = verify_token(token, get_settings().license_public_key, device_id)
    with session_scope() as s:
        s.query(DeviceLicense).delete()
        s.add(DeviceLicense(token=token.strip(), device_id=device_id, licensee=info.name, expires=info.expires))
    return license_status(force=True)


def deactivate() -> dict:
    from app.db import session_scope
    from app.models import DeviceLicense

    with session_scope() as s:
        s.query(DeviceLicense).delete()
    return license_status(force=True)


def invalidate_cache() -> None:
    with _lock:
        _cache.update(checked_at=0.0, status=None)
