.PHONY: up down db-check hardware lint test

up:
	docker compose up -d --wait

down:
	docker compose down

db-check:
	docker compose exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -tAc "select extname from pg_extension order by 1"'

hardware:
	python scripts/capture_hardware.py

lint:
	python -m ruff check scripts

test:
	python -m pytest tests -q
