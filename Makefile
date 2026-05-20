.PHONY: setup fmt lint type test ci up down status ingest

# ── Dev workflow ─────────────────────────────────────────────────────
setup:  ## Create venv, install deps, install pre-commit hooks
	uv venv .venv
	uv pip install -e ".[dev]"
	uv run pre-commit install

fmt:  ## Format code with ruff
	ruff format .

lint:  ## Lint code with ruff
	ruff check .

type:  ## Type-check with mypy
	mypy .

test:  ## Run tests with coverage
	pytest --cov=access_iq

ci: fmt lint type test  ## Run full CI pipeline

# ── Infrastructure (CDK) ────────────────────────────────────────────
infra-bootstrap:  ## Bootstrap CDK (requires AWS_PROFILE, CDK_ENV)
	cd infra && uv run cdk bootstrap -c "env=$${CDK_ENV:-dev}"

infra-diff:  ## Show CDK diff
	cd infra && uv run cdk diff -c "env=$${CDK_ENV:-dev}"

infra-deploy:  ## Deploy CDK stacks (optional CDK_STACK=<name>)
	cd infra && uv run cdk deploy $${CDK_STACK:---all} -c "env=$${CDK_ENV:-dev}" --require-approval never

infra-destroy:  ## Destroy CDK stacks
	cd infra && uv run cdk destroy --all --force -c "env=$${CDK_ENV:-dev}"

# ── Session orchestration ───────────────────────────────────────────
up:  ## Deploy Trust + Platform stacks
	./scripts/session.sh up

down:  ## Destroy all stacks
	./scripts/session.sh down

status:  ## Show current stack states
	./scripts/session.sh status

ingest:  ## Run Bronze ingestion on ECS Fargate (3 parallel tasks)
	./scripts/session.sh ingest
