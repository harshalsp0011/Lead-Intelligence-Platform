# Unified Agent Service Container
# Runs all agents (analyst, scout, orchestrator, writer, outreach, tracker)
# Orchestration handled by Airflow scheduler

FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY requirements.txt .
COPY agents/ ./agents/
COPY config/ ./config/
COPY database/ ./database/
COPY data/ ./data/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port for health checks (optional)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default: agents are called by Airflow
# If running directly as service, provide entry point
CMD ["python", "-m", "agents.orchestrator.orchestrator"]
