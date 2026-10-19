@echo off
REM Stops MarketWatch. Your data is kept; double-click start.bat to resume.
cd /d "%~dp0"
docker compose down
echo MarketWatch stopped. Your watchlist and portfolio are saved.
pause
