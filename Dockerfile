# SmartNav server image. Builds for Intel/AMD (amd64) and ARM (arm64),
# so it runs on most Synology models, a Raspberry Pi or a cheap VPS.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SMARTNAV_DATA_DIR=/data

WORKDIR /app
COPY sdk ./sdk
COPY plugins ./plugins
COPY server ./server
RUN pip install ./sdk ./plugins ./server

# Extra club plugins: list pip requirements in /data/plugins.txt and restart.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data

# Runs as root inside the container so it can always write to the mounted
# data folder (on a Synology that folder belongs to your NAS account).
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
ENTRYPOINT ["/entrypoint.sh"]
CMD ["smartnav", "serve", "--host", "0.0.0.0", "--port", "8000"]
