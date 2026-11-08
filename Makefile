# Single command runner. Requires: docker (with compose v2) and make.
COMPOSE_TEST = docker compose -f docker-compose.test.yml
RUN_DEV      = $(COMPOSE_TEST) run --rm dev

.PHONY: up down logs test check format load-test clean

# Random local passwords, generated once, never committed (.env is git-ignored).
.env:
	@echo "Generating .env with random local passwords"
	@printf 'POSTGRES_PASSWORD=%s\nRABBITMQ_PASSWORD=%s\n' \
	  "$$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(16))')" \
	  "$$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(16))')" > .env

up: .env  ## build and boot everything (postgres, rabbitmq, api, worker)
	docker compose up --build -d --wait
	@echo ""
	@echo "API:          http://localhost:8000   (docs: http://localhost:8000/docs)"
	@echo "RabbitMQ UI:  http://localhost:15672  (user: controlplane, password in .env)"

down:
	docker compose down

logs:
	docker compose logs -f api worker

test: .env  ## full automated test suite (spins up throwaway postgres + rabbitmq)
	$(COMPOSE_TEST) build dev
	$(RUN_DEV) pytest --cov --cov-report=term-missing; rc=$$?; \
	  $(COMPOSE_TEST) down -v --remove-orphans; exit $$rc

check: .env  ## ALL quality gates: lint + format check + security scan + tests
	$(COMPOSE_TEST) build dev
	$(RUN_DEV) sh scripts/check.sh; rc=$$?; \
	  $(COMPOSE_TEST) down -v --remove-orphans; exit $$rc

format: .env  ## format and auto-fix the sources in your working tree
	$(COMPOSE_TEST) build dev
	$(COMPOSE_TEST) run --rm --no-deps dev sh -c "ruff check --fix src tests; ruff format src tests"

load-test:  ## race-condition demo against the running stack
	docker compose exec api python -m controlplane.tools.load_test

clean:  ## stop everything and delete volumes and the generated .env
	docker compose down -v --remove-orphans
	rm -f .env
