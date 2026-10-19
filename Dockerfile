# SnitchofDalal - Indian stock market sentiment & technical intelligence
# Build:  docker build -t snitchofdalal .
# Run:    docker compose up -d   (see docker-compose.yml)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Kolkata \
    DATA_DIR=/data

WORKDIR /app

# Install dependencies first so Docker caches this layer between code changes.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY tools ./tools
COPY pyproject.toml .

# Run as an unprivileged user; /data is the persistent volume for SQLite + outbox.
RUN useradd --create-home --uid 10001 snitchofdalal \
    && mkdir -p /data && chown -R snitchofdalal:snitchofdalal /data /app
USER snitchofdalal
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
