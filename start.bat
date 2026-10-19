@echo off
REM SnitchofDalal one-click start (Windows). Double-click this file.
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker is not installed.
  echo Install Docker Desktop from https://www.docker.com/products/docker-desktop/ then run this again.
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo Docker is installed but not running. Open Docker Desktop, wait for it to say "running", then run this again.
  pause
  exit /b 1
)
if not exist .env (
  echo # Per-machine overrides. Defaults for everyone live in .env.example.> .env
  echo # Add only the lines you want to change, e.g. APP_PORT=8010>> .env
  echo Created .env ^(overrides only; shared defaults come from .env.example^).
)
REM An empty "KEY=" line in .env would blank out a default from .env.example; drop such lines.
powershell -NoProfile -Command "(Get-Content .env) | Where-Object { $_ -notmatch '^[A-Za-z_][A-Za-z0-9_]*=\s*$' } | Set-Content .env" >nul 2>nul

echo Starting SnitchofDalal (first start downloads ~400 MB and can take a few minutes)...
REM Prefer the prebuilt image; if it cannot be pulled, build from this folder so updates
REM to the code are always picked up.
docker compose pull --quiet >nul 2>nul
if errorlevel 1 (
  docker compose up -d --build
) else (
  docker compose up -d
)
if errorlevel 1 (
  echo Something went wrong. Scroll up for the error, or run: docker compose logs
  pause
  exit /b 1
)

set PORT=%APP_PORT%
if "%PORT%"=="" set PORT=8000
echo Waiting for the app to come up...
timeout /t 15 /nobreak >nul

echo.
echo SnitchofDalal is running at http://localhost:%PORT%
echo To stop it: double-click stop.bat   ^|   To see logs: docker compose logs -f
start "" http://localhost:%PORT%
pause
