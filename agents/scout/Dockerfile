FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
	gcc \
	postgresql-client \
	libasound2 \
	libatk-bridge2.0-0 \
	libatk1.0-0 \
	libcups2 \
	libdbus-1-3 \
	libdrm2 \
	libexpat1 \
	libgbm1 \
	libglib2.0-0 \
	libgtk-3-0 \
	libnspr4 \
	libnss3 \
	libx11-6 \
	libxcb1 \
	libxcomposite1 \
	libxdamage1 \
	libxext6 \
	libxfixes3 \
	libxkbcommon0 \
	libxrandr2 \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY agents/ ./agents/
COPY config/ ./config/
COPY database/ ./database/
COPY data/ ./data/

RUN pip install --no-cache-dir -r requirements.txt \
	&& python -m playwright install chromium

ENV PYTHONPATH=/app

CMD ["python", "-m", "agents.scout.scout_agent"]
