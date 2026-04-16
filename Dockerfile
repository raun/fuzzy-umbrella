FROM python:3.12-slim

WORKDIR /workspace

# System deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dev dependencies early so they are cached
COPY pyproject.toml* ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir pytest pytest-cov pytest-mock ruff pyright

# Project source is mounted at runtime — do not COPY here
CMD ["sleep", "infinity"]
