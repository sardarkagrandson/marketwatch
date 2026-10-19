# Installing MarketWatch (no programming needed)

MarketWatch runs on your own computer inside a small container, so nothing
else has to be installed except Docker Desktop. It works on Windows 10/11,
macOS and Linux. Allow about 10 minutes the first time.

## Step 1 - Install Docker Desktop (one time)

1. Go to https://www.docker.com/products/docker-desktop/ and download the
   version for your computer (Windows, Mac with Apple chip, Mac with Intel chip, or Linux).
2. Install it like any other program and open it.
3. Wait until Docker Desktop shows a green "Engine running" status at the
   bottom left. On Windows it may ask you to install WSL 2; accept and restart
   if prompted.

You do not need a Docker account; skip or close the sign-in screen.

## Step 2 - Get MarketWatch

Download the project as a ZIP from GitHub (the green **Code** button, then
**Download ZIP**) and unzip it somewhere easy to find, for example your
Documents folder. You should see files named `start.bat`, `start.sh` and
`docker-compose.yml` inside.

## Step 3 - Start it

- **Windows:** double-click `start.bat`.
- **Mac:** right-click `start.sh`, choose *Open With > Terminal*
  (or in Terminal run `./start.sh` from the folder).
- **Linux:** run `./start.sh` in a terminal.

The first start downloads about 400 MB and takes a few minutes. When it is
ready your browser opens http://localhost:8000. If it does not, open that
address yourself.

Docker keeps MarketWatch running in the background, even after you close the
window, and restarts it automatically when your computer turns on and Docker
Desktop starts. Spotlight alerts therefore keep polling as long as the
computer is awake and Docker is running.

## Stopping and updating

- **Stop:** double-click `stop.bat` (Windows) or run `./stop.sh`. Your
  watchlist, portfolio and saved alerts are kept.
- **Start again:** run the start script again.
- **Update to a newer version:** download the new ZIP, unzip it over the old
  folder (keep your `.env` file), then run the start script. Data is stored in a
  Docker volume, not in the folder, so it survives updates.

## Optional settings (the `.env` file)

The start script creates a file called `.env` next to it. Open it in Notepad
or TextEdit to switch features on:

| Setting | What it does |
|---|---|
| `ANTHROPIC_API_KEY=` | Paste an Anthropic API key to have news classified by Claude. Without it a built-in keyword classifier is used (the app tells you which one is active). |
| `SMTP_HOST=`, `SMTP_PORT=`, `SMTP_USERNAME=`, `SMTP_PASSWORD=`, `SMTP_FROM=` | Email account used to send alerts. For Gmail use `smtp.gmail.com`, port `587`, and an *App Password* (not your normal password). Without these, alert emails are saved as files instead of sent. |
| `OFFLINE_MODE=true` | Use sample data with no internet. Handy for trying the interface. |
| `MARKET_HOLIDAYS=` | Dates like `2026-10-20,2026-11-05` on which polling is skipped. |

After changing `.env`, run the start script again so the new settings apply.

## Where are the saved alert emails?

When email is not configured, each alert is saved as an HTML file inside the
container's data volume. To copy them out:

```
docker cp marketwatch:/data/outbox ./alerts
```

## Something is not working?

| Problem | What to do |
|---|---|
| "Docker is not installed" or "not running" | Open Docker Desktop and wait for the green status, then retry. |
| Browser shows "connection refused" | Wait 30 seconds and refresh; the first start is slow. |
| Port 8000 is already used by another program | Add a line `MARKETWATCH_PORT=8010` to `.env` and start again; then open http://localhost:8010. |
| Prices show "previous-session close" | Normal outside NSE hours (09:15 to 15:30 IST, Monday to Friday). |
| News matrix is empty | Check your internet connection; feeds are cached for 30 minutes. |
| See what is happening inside | Run `docker compose logs -f` in the folder. |

MarketWatch shows statistical and news-derived biases only. It is not
investment advice; equity investments are subject to market risk.
