# ==============================================================================
# Production Dockerfile for InstaPay Verification Microservice & Merchant Portal
# ==============================================================================
FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install runtime dependencies (curl for healthchecks & font utilities for PDF generator)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application backend and frontend assets
COPY app/ /app/app/
COPY static/ /app/static/
COPY DEVELOPER_INTEGRATION_GUIDE.md /app/DEVELOPER_INTEGRATION_GUIDE.md

# Create persistent data directory for SQLite database
RUN mkdir -p /app/data

# Expose microservice HTTP port
EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start Uvicorn ASGI server with 2 workers and reverse-proxy header support
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
