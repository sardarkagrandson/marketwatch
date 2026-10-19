#!/usr/bin/env python3
"""Compile app/static/tailwind.css from the templates. Dev-only; the result is committed.

    pip install pytailwindcss
    python tools/build_css.py            # minified build
    python tools/build_css.py --watch    # rebuild on change
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        import pytailwindcss
    except ImportError:
        sys.exit("pip install pytailwindcss")
    args = ["-c", str(ROOT / "tailwind.config.js"), "-i", str(ROOT / "app/static/tailwind.src.css"),
            "-o", str(ROOT / "app/static/tailwind.css")]
    args += ["--watch"] if "--watch" in sys.argv else ["--minify"]
    return pytailwindcss.run(args, auto_install=True, version="v3.4.17")


if __name__ == "__main__":
    raise SystemExit(main())
