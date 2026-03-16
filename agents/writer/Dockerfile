FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     gcc     postgresql-client     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY agents/ ./agents/
COPY config/ ./config/
COPY database/ ./database/
COPY data/ ./data/

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app

CMD ["python", "-m", "agents.writer.writer_agent"]
