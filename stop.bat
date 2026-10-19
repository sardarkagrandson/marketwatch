@echo off
REM Stops SnitchofDalal. Your data is kept; double-click start.bat to resume.
cd /d "%~dp0"
docker compose down
echo SnitchofDalal stopped. Your watchlist and portfolio are saved.
pause
