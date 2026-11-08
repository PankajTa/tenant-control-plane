# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

# ---- runtime: used by `api` and `worker` ------------------------------------------------
FROM base AS runtime
RUN pip install . && useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["python", "-m", "controlplane"]

# ---- dev: lint, format, security scan, tests --------------------------------------------
FROM base AS dev
RUN pip install -e ".[dev]"
COPY tests ./tests
COPY scripts ./scripts
CMD ["pytest", "--cov", "--cov-report=term-missing"]
