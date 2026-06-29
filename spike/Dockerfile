# Calma verification backend. A real container (not serverless): it git-clones repos and orchestrates E2B
# microVMs. Untrusted repo code runs in E2B (CALMA_FORCE_E2B=1), never on this host.
FROM python:3.12-slim

# git: clone repos at a pinned commit. openssl: RS256 JWT minting for the GitHub App (no PyJWT/cryptography).
RUN apt-get update && apt-get install -y --no-install-recommends git openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# the engine: core + runner + discovery + synth + recipes + connect + capture + server
COPY . /app

# capture/sitecustomize.py must be importable so it auto-arms inside runs (PYTHONPATH includes capture/)
ENV PYTHONPATH=/app:/app/capture \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    CALMA_FORCE_E2B=1
EXPOSE 8080

# bind 0.0.0.0 (the server's __main__ binds 127.0.0.1, which is unreachable in a container) and read $PORT
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
