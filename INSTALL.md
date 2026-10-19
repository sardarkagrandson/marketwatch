# Installing SnitchofDalal (no programming needed)

SnitchofDalal runs on your own computer inside a small container, so nothing
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

## Step 2 - Get SnitchofDalal

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

Docker keeps SnitchofDalal running in the background, even after you close the
window, and restarts it automatically when your computer turns on and Docker
Desktop starts. Spotlight alerts therefore keep polling as long as the
computer is awake and Docker is running.

## First launch: activating your device

If the app shows an **Activate this device** screen, copy the Device ID it displays
(for example `7F3A-91C2-0B5E-44D1`) and send it to us. We reply with a licence key
starting with `SOD1.`; paste it into the box and click **Activate**. This is done
once per computer. A key issued for another computer, or an expired key, will not
work; ask us for a new one.

## Stopping and updating

- **Stop:** double-click `stop.bat` (Windows) or run `./stop.sh`. Your
  watchlist, portfolio and saved alerts are kept.
- **Start again:** run the start script again.
- **Update to a newer version:** download the new ZIP, unzip it over the old
  folder (keep your `.env` file), then run the start script. It rebuilds the app
  from the new files. Data is stored in a Docker volume, not in the folder, so it
  survives updates.

### Upgrading from the first release (named "MarketWatch")

The first release used the name *marketwatch* for its container and data volume.
Before starting the new version once, remove the old container so the port is
free (your data volume is not touched by this):

```
docker rm -f marketwatch
```

Then run the start script as usual. The new version starts with an empty
watchlist and portfolio. If you want to carry over what you had, run this once
after the new version has started at least once, then restart it:

```
docker run --rm -v marketwatch_marketwatch-data:/from -v snitchofdalal_snitchofdalal-data:/to alpine sh -c "cp -a /from/. /to/ && mv /to/marketwatch.db /to/snitchofdalal.db"
docker compose restart
```

(If your folder was not called `marketwatch` or `snitchofdalal`, list the volume
names with `docker volume ls` and substitute them.) Once you are happy, the old
volume can be removed with `docker volume rm marketwatch_marketwatch-data`.

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
docker cp snitchofdalal:/data/outbox ./alerts
```

## Something is not working?

| Problem | What to do |
|---|---|
| "Docker is not installed" or "not running" | Open Docker Desktop and wait for the green status, then retry. |
| Browser shows "connection refused" | Wait 30 seconds and refresh; the first start is slow. |
| After an update the page looks or behaves like the old version | Hard-refresh once: Ctrl+F5 on Windows, Cmd+Shift+R on Mac. |
| Status bar says "Keyword news scoring" | Normal without an AI key. News is scored with a built-in keyword dictionary. Add `ANTHROPIC_API_KEY` in `.env` to use AI scoring. |
| Port 8000 is already used by another program | Add a line `APP_PORT=8010` to `.env` and start again; then open http://localhost:8010. |
| Want to open it from your phone or another PC on the same Wi-Fi | Add `BIND_HOST=0.0.0.0` to `.env`, start again, and use your computer's IP address, e.g. http://192.168.1.20:8000. |
| "Activate this device" appears again | Your licence has expired or the app's data was reset. Send us the new Device ID for a fresh key. |
| Prices show "previous-session close" | Normal outside NSE hours (09:15 to 15:30 IST on trading days). The status bar shows when the market next opens. During market hours prices come from NSE directly; if NSE is unreachable they come from Yahoo Finance, which can lag by up to 15 minutes. |
| News matrix is empty | Check your internet connection; feeds are cached for 30 minutes. |
| See what is happening inside | Run `docker compose logs -f` in the folder. |

SnitchofDalal shows statistical and news-derived biases only. It is not
investment advice; equity investments are subject to market risk.
