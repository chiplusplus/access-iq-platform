.PHONY: setup fmt lint type test test-integration ci up down status ingest dbt tunnel tunnel-stop tunnel-env

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

test:  ## Run unit tests with coverage
	pytest --cov=access_iq

test-integration:  ## Run integration tests against live AWS (requires deployed stacks)
	pytest -m integration --no-header -v

ci: fmt lint type test  ## Run full CI pipeline

# ── Infrastructure (CDK) ────────────────────────────────────────────
# TRUST_VPC_ID is required for NetworkStack (peering). Get it from Trust CFN outputs or `make status`.
# Example: make infra-deploy TRUST_VPC_ID=vpc-0abc123
AWS_PROFILE ?= CHI-Engineer-222308823356
CDK_CONTEXT := -c "env=$${CDK_ENV:-dev}" $(if $(TRUST_VPC_ID),-c "trust_vpc_id=$(TRUST_VPC_ID)") --profile $(AWS_PROFILE)

infra-bootstrap:  ## Bootstrap CDK (requires AWS_PROFILE, CDK_ENV)
	cd infra && uv run cdk bootstrap $(CDK_CONTEXT)

infra-diff:  ## Show CDK diff
	cd infra && uv run cdk diff $(CDK_CONTEXT)

CDK_DEPLOY_TARGET := $(if $(CDK_STACK),$(CDK_STACK),--all)

infra-deploy:  ## Deploy CDK stacks (optional CDK_STACK=<name>, TRUST_VPC_ID=vpc-xxx)
	cd infra && uv run cdk deploy $(CDK_DEPLOY_TARGET) $(CDK_CONTEXT) --require-approval never

infra-destroy:  ## Destroy CDK stacks
	cd infra && uv run cdk destroy --all --force $(CDK_CONTEXT)

# ── Session orchestration ───────────────────────────────────────────
up:  ## Deploy Trust + Platform stacks (SKIP_GENERATE=1 reuse data, SKIP_SEED=1 infra only)
	./scripts/session.sh up $(if $(SKIP_GENERATE),--skip-generate) $(if $(SKIP_SEED),--skip-seed)

down:  ## Destroy all stacks
	./scripts/session.sh down

status:  ## Show current stack states
	./scripts/session.sh status

ingest:  ## Run Bronze ingestion on ECS Fargate (3 parallel tasks)
	./scripts/session.sh ingest

dbt:  ## Run dbt command (e.g., make dbt CMD="run --select silver")
	eval $$(./scripts/tunnel.sh env) && cd dbt && uv run dbt $(CMD) --profiles-dir .

# ── Redshift tunnel ────────────────────────────────────────────────
tunnel:  ## Start SSM port-forwarding tunnel to Redshift (localhost:5439, foreground)
	./scripts/tunnel.sh

tunnel-stop:  ## Kill background SSM tunnel started by make up
	@if [ -f .tunnel.pid ]; then \
		pid=$$(cat .tunnel.pid); \
		if kill -0 "$$pid" 2>/dev/null; then \
			kill "$$pid" && echo "Killed tunnel (PID $$pid)"; \
		else \
			echo "Tunnel not running (stale PID $$pid)"; \
		fi; \
		rm -f .tunnel.pid; \
	else \
		echo "No .tunnel.pid file — tunnel not managed by make up"; \
	fi

tunnel-env:  ## Print export commands for dbt Redshift credentials
	@./scripts/tunnel.sh env
