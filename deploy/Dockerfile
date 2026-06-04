# Reachly — standalone agent OR SaaS server in one image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for Playwright (browser mode). Drop these if you only use API mode.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation libnss3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt
RUN python -m playwright install chromium

COPY . .

# --- Standalone agent (default) ---
# Provide config via env or a mounted .env file.
CMD ["python", "-m", "reachly.runner", "run"]

# --- SaaS server (override the command) ---
# docker run ... reachly uvicorn server.app:app --host 0.0.0.0 --port 8000
