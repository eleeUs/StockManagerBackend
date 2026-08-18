.PHONY: help build up down migrate seed test test-v coverage lint shell logs prod-up

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

test: ## Run the test suite
	docker-compose exec api pytest --tb=short -q

test-v: ## Run the test suite verbosely
	docker-compose exec api pytest -v

coverage: ## Run tests with coverage (term + html)
	docker-compose exec api pytest
	@echo "HTML report ready at ./htmlcov/index.html (source is bind-mounted, no copy needed)"

lint: ## Run ruff checks
	docker-compose exec api ruff check .

shell: ## Open a Django shell_plus session
	docker-compose exec api python manage.py shell_plus

logs: ## Tail the api container logs
	docker-compose logs -f api

prod-up: ## Start the production stack
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
