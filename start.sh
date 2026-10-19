#!/usr/bin/env bash
# MarketWatch one-click start (macOS / Linux). Double-click or run: ./start.sh
set -e
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed."
  echo "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ then run this again."
  read -r -p "Press Enter to close..." _
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not running. Open Docker Desktop, wait for it to say 'running', then run this again."
  read -r -p "Press Enter to close..." _
  exit 1
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (edit it later to add email or AI settings)."
fi

echo "Starting MarketWatch (first start downloads ~400 MB and can take a few minutes)..."
# Prefer the prebuilt image; if it is not available, compose builds it locally.
docker compose pull --ignore-pull-failures --quiet >/dev/null 2>&1 || true
docker compose up -d

PORT="${MARKETWATCH_PORT:-8000}"
URL="http://localhost:${PORT}"
echo "Waiting for the app to come up..."
for _ in $(seq 1 60); do
  if curl -fs "${URL}/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done

echo ""
echo "MarketWatch is running at ${URL}"
echo "To stop it: ./stop.sh   |   To see logs: docker compose logs -f"
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then open "$URL" || true; fi
