#!/bin/sh
# All quality gates; runs inside the dev container (`make check`).
set -eu
echo "==> lint (ruff check)";          ruff check src tests
echo "==> format (ruff format --check)"; ruff format --check src tests
echo "==> security scan (bandit)";     bandit -q -r src -c pyproject.toml
echo "==> tests + coverage (pytest)";  pytest --cov --cov-report=term-missing
echo "ALL CHECKS PASSED"
