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
COPY submissions_data.json ./ 2>/dev/null || true

# Copy example env (not used in production unless overridden)
COPY .env.example ./

# Expose health port
EXPOSE 7890

# Default env placeholders (override at runtime)
ENV HEALTH_PORT=7890

# Run bot
CMD ["python", "bot.py"]
