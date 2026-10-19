#!/usr/bin/env python3
"""Operator tool for SnitchofDalal device licences.

  python tools/license_admin.py keygen                      # once; prints LICENSE_PUBLIC_KEY
  python tools/license_admin.py issue --device-id AB12-... --name "Ravi K" --days 365
  python tools/license_admin.py inspect <token>
  python tools/license_admin.py list                        # issued_licenses.csv next to the key

Inside Docker (no Python needed on the host), keep the key in the data volume:
  docker compose exec snitchofdalal python tools/license_admin.py keygen --out /data/license_private.pem
  docker compose exec snitchofdalal python tools/license_admin.py issue --key /data/license_private.pem --device-id ... --name ...

Keep license_private.pem secret and out of git (it is in .gitignore).
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.licensing import decode_token, generate_keypair, issue_token, load_private_key  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

DEFAULT_KEY = ROOT / "license_private.pem"


def ledger_for(key_path: str | Path) -> Path:
    return Path(key_path).resolve().parent / "issued_licenses.csv"


def cmd_keygen(args):
    out = Path(args.out)
    if out.exists() and not args.force:
        sys.exit(f"{out} already exists; pass --force to overwrite (this invalidates all issued licences).")
    pem, pub = generate_keypair()
    out.write_text(pem)
    out.chmod(0o600)
    print(f"Private key written to {out} (keep it secret).")
    print("Add this line to .env.example / .env before building the image:\n")
    print(f"LICENSE_PUBLIC_KEY={pub}")


def cmd_issue(args):
    pem = Path(args.key).read_text()
    token = issue_token(pem, args.device_id, args.name, None if args.days == 0 else args.days, args.plan)
    ledger = ledger_for(args.key)
    new = not ledger.exists()
    with ledger.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["issued_at", "device_id", "name", "days", "plan", "token"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), args.device_id.upper(), args.name, args.days, args.plan, token])
    print(f"Licence for {args.name} on device {args.device_id.upper()} ({'no expiry' if args.days == 0 else f'{args.days} days'}):\n")
    print(token)
    print(f"\nRecorded in {ledger}")


def cmd_inspect(args):
    payload, _, _ = decode_token(args.token)
    for k, v in payload.items():
        print(f"{k:10} {v}")
    if args.key and Path(args.key).exists():
        pub = load_private_key(Path(args.key).read_text()).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        from app.licensing import _b64e, verify_token

        try:
            verify_token(args.token, _b64e(pub))
            print("signature  valid for the local private key")
        except Exception as exc:
            print(f"signature  INVALID: {exc}")


def cmd_list(args):
    ledger = ledger_for(args.key)
    if not ledger.exists():
        print("No licences issued yet.")
        return
    with ledger.open() as fh:
        for row in csv.DictReader(fh):
            print(f"{row['issued_at']}  {row['device_id']}  {row['name']:24} {row['days']:>5}d  {row['plan']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen"); k.add_argument("--out", default=str(DEFAULT_KEY)); k.add_argument("--force", action="store_true")
    i = sub.add_parser("issue")
    i.add_argument("--device-id", required=True); i.add_argument("--name", required=True)
    i.add_argument("--days", type=int, default=365, help="0 = never expires"); i.add_argument("--plan", default="standard")
    i.add_argument("--key", default=str(DEFAULT_KEY))
    n = sub.add_parser("inspect"); n.add_argument("token"); n.add_argument("--key", default=str(DEFAULT_KEY))
    l = sub.add_parser("list"); l.add_argument("--key", default=str(DEFAULT_KEY))
    args = p.parse_args()
    {"keygen": cmd_keygen, "issue": cmd_issue, "inspect": cmd_inspect, "list": cmd_list}[args.cmd](args)


if __name__ == "__main__":
    main()
