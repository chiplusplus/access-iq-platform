.PHONY: setup install fmt lint type test ci

ENV= . .venv/bin/activate
setup:
	uv venv
	$(ENV) && uv pip install -e ".[dev]"
	$(ENV) && pre-commit install

install:
	$(ENV) && uv pip install -e .

fmt:
	$(ENV) && ruff format .

lint:
	$(ENV) && ruff check .

type:
	$(ENV) && mypy .

test:
	$(ENV) && pytest --cov=access_iq

ci: fmt lint type test
