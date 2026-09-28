.PHONY: help build up down migrate seed test test-v coverage lint shell logs prod-up pre-commit-install pre-commit-run pgb-userlist pgb-pools pgb-stats pgb-clients prod-migrate

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: ## Build the docker images
	docker-compose build

up: ## Start the development stack
	docker-compose up

down: ## Stop the development stack
	docker-compose down

migrate: ## Apply database migrations
	docker-compose exec api python manage.py migrate

seed: ## Load development seed data
	docker-compose exec api python manage.py seed_dev_data

# DJANGO_SETTINGS_MODULE is forced to config.settings.test here because
# .env sets it to config.settings.development for `runserver`/`migrate`,
# and that becomes a real container env var via docker-compose's
# `env_file:` — which pytest-django would otherwise prefer over
# pytest.ini, silently re-enabling django-silk during test runs.
# See config/settings/test.py and docs/phase-9-bugfix-plan.md §4.
test: ## Run the test suite
	docker-compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest --tb=short -q

test-v: ## Run the test suite verbosely
	docker-compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest -v

coverage: ## Run tests with coverage (term + html)
	docker-compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest
	@echo "HTML report ready at ./htmlcov/index.html (source is bind-mounted, no copy needed)"

lint: ## Run ruff checks
	docker-compose exec api ruff check .

shell: ## Open a Django shell_plus session
	docker-compose exec api python manage.py shell_plus

logs: ## Tail the api container logs
	docker-compose logs -f api

prod-up: ## Start the production stack
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# One-off commands that must bypass PgBouncer (migrations need a direct,
# non-pooled connection — see docs/infra/pgbouncer.md §Direct access).
# Overrides DATABASE_URL back to db:5432 for this single invocation only;
# the running `api` container keeps using pgbouncer:6432 for everything else.
prod-migrate: ## Apply migrations against Postgres directly, bypassing PgBouncer
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
		run --rm -e DATABASE_URL=postgres://stock_user:stock_password@db:5432/stock_db \
		api python manage.py migrate

# See docker/pgbouncer/userlist.txt.example for what this generates and why.
pgb-userlist: ## Regenerate docker/pgbouncer/userlist.txt from pg_shadow (run after rotating pgbouncer_auth's password)
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
		exec db psql -U stock_user -d stock_db -tAc \
		"SELECT concat('\"', usename, '\" \"', passwd, '\"') FROM pg_shadow WHERE usename = 'pgbouncer_auth'" \
		> docker/pgbouncer/userlist.txt
	@echo "Wrote docker/pgbouncer/userlist.txt — restart pgbouncer to pick it up: docker-compose -f docker-compose.yml -f docker-compose.prod.yml restart pgbouncer"

pgb-pools: ## Show PgBouncer pool state (cl_active, cl_waiting, sv_active, sv_idle, maxwait)
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
		exec pgbouncer psql -h 127.0.0.1 -p 6432 -U pgbouncer_auth pgbouncer -c "SHOW POOLS;"

pgb-stats: ## Show PgBouncer throughput stats (avg_xact_time, avg_wait_time, ...)
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
		exec pgbouncer psql -h 127.0.0.1 -p 6432 -U pgbouncer_auth pgbouncer -c "SHOW STATS;"

pgb-clients: ## Show connected PgBouncer clients and how long each has been waiting
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
		exec pgbouncer psql -h 127.0.0.1 -p 6432 -U pgbouncer_auth pgbouncer -c "SHOW CLIENTS;"

# These two run on your HOST, not through docker-compose exec like
# everything else in this file — git hooks fire from your local git
# client when you run `git commit`, which happens outside any
# container, and this project's image doesn't have git installed
# anyway. Needs Python + pip available locally (see requirements/development.txt
# for the pre-commit version pin).
pre-commit-install: ## One-time setup: install the git hook (runs on host)
	pip install pre-commit
	pre-commit install

pre-commit-run: ## Run all hooks against every file, without committing (runs on host)
	pre-commit run --all-files
