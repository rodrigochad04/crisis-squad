FROM python:3.11-slim AS base

LABEL org.opencontainers.image.title="GCB Autonomous Crisis Squad"
LABEL org.opencontainers.image.description="AI-native incident response with Human-in-the-Loop governance"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies come from pyproject.toml and nowhere else, so the image can never
# drift from the package definition. setuptools needs the package tree present,
# so src/ is copied before the install. No `|| fallback`: if the install breaks,
# the build must fail loudly rather than silently produce a half-working image.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY . .

# Drop privileges — nothing in this service needs root.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
