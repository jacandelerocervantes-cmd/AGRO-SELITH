# PostGIS debe estar arriba (make up)
.PHONY: fusion export-engine migrate seed up down demo check lint types test validate-knowledge e2e deploy demo-script rename

up:
	docker compose up -d db

down:
	docker compose down

migrate:
	cd apps/api && uv run alembic upgrade head

seed:
	uv run python apps/api/seed.py knowledge

fusion:
	uv run python scripts/cargar_fusion.py demo
	uv run python scripts/cargar_capas.py demo

export-engine:
	uv run python tools/export_engine_data.py

validate-knowledge:
	uv run python tools/validate_knowledge.py knowledge

lint:
	uv run ruff check .

types:
	uv run mypy packages/engine/src tools pipelines/milpa_pipelines apps/api/milpa_api

test:
	uv run pytest --cov=milpa_engine --cov-report=term-missing

check: lint types validate-knowledge test


demo:
	uv run python -m milpa_engine --escenario canicula_prolongada

e2e:
	cd apps/web && npx playwright test

deploy:
	pwsh ./scripts/deploy.ps1 -Grupo $(GRUPO) -Ubicacion $(or $(UBICACION),eastus2)

demo-script:
	@echo "El flujo de la demo está automatizado en apps/web/e2e/producto.spec.ts (make e2e)"

rename:
	uv run python scripts/rename.py "$(NAME)"
