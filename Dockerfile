# Python slim base
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Install system deps (optional: timezone data)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY bot.py ./

# Create data directory (volume will mount here)
RUN mkdir -p /data

# Copy example env (not used in production unless overridden)
COPY .env.example ./

# Expose health port
EXPOSE 7890

# Default env placeholders (override at runtime)
ENV HEALTH_PORT=7890 \
  DATA_DIR=/data

# Run bot
CMD ["python", "bot.py"]
