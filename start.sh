#!/usr/bin/env bash
# SnitchofDalal one-click start (macOS / Linux). Double-click or run: ./start.sh
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
  printf '# Per-machine overrides. Defaults for everyone live in .env.example.\n# Add only the lines you want to change, e.g. APP_PORT=8010\n' > .env
  echo "Created .env (overrides only; shared defaults come from .env.example)."
fi
# An empty "KEY=" line in .env would blank out a default from .env.example; drop such lines.
sed -i.bak -E '/^[A-Za-z_][A-Za-z0-9_]*=[[:space:]]*$/d' .env && rm -f .env.bak

echo "Starting SnitchofDalal (first start downloads ~400 MB and can take a few minutes)..."
# Prefer the prebuilt image; if it cannot be pulled, build from this folder so updates
# to the code are always picked up.
if docker compose pull --quiet >/dev/null 2>&1; then
  docker compose up -d
else
  docker compose up -d --build
fi

PORT="${APP_PORT:-8000}"
URL="http://localhost:${PORT}"
echo "Waiting for the app to come up..."
for _ in $(seq 1 60); do
  if curl -fs "${URL}/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done

echo ""
echo "SnitchofDalal is running at ${URL}"
echo "To stop it: ./stop.sh   |   To see logs: docker compose logs -f"
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then open "$URL" || true; fi
