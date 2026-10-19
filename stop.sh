#!/usr/bin/env bash
# Stops SnitchofDalal. Your data is kept; run ./start.sh to resume.
cd "$(dirname "$0")"
docker compose down
echo "SnitchofDalal stopped. Your watchlist and portfolio are saved."
