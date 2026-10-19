#!/usr/bin/env bash
# Stops MarketWatch. Your data is kept; run ./start.sh to resume.
cd "$(dirname "$0")"
docker compose down
echo "MarketWatch stopped. Your watchlist and portfolio are saved."
