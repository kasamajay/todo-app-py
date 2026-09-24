# All targets wrap docker compose - no native Python/Node/npm installation is
# required. Windows users without `make` can run the underlying
# `docker compose ...` commands directly (see README.md).

install-tools:
	docker compose build

dev-api:
	docker compose up api

dev-web:
	docker compose up web

dev:
	docker compose up

test:
	docker compose run --rm api pytest

build:
	docker compose build

down:
	docker compose down

# Production mode: nginx serves the prebuilt bundle, no Node at runtime.
prod-build:
	docker compose -f docker-compose.prod.yml build

prod-up:
	docker compose -f docker-compose.prod.yml up -d --build

prod-down:
	docker compose -f docker-compose.prod.yml down

.PHONY: install-tools dev-api dev-web dev test build down prod-build prod-up prod-down
