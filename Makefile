.PHONY: setup check-prereqs fmt lint type test test-integration ci profile ready dq-gate up down status ingest pipeline dbt rs-tunnel tunnel-stop tunnel-env reconnect dashboard

# ── Dev workflow ─────────────────────────────────────────────────────
setup: check-prereqs  ## Create venv, install all workspace members + dev deps, install pre-commit hooks
	uv sync --group dev
	uv run pre-commit install
	@echo "\n✅ Setup complete. Run 'source .venv/bin/activate' or use 'make' targets directly."

check-prereqs:  ## Verify required CLI tools are installed
	@command -v uv >/dev/null 2>&1 || { echo "❌ uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "❌ node not found. Install: https://nodejs.org/"; exit 1; }
	@command -v cdk >/dev/null 2>&1 || { echo "❌ aws-cdk CLI not found. Install: npm install -g aws-cdk"; exit 1; }
	@command -v aws >/dev/null 2>&1 || { echo "❌ aws CLI not found. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"; exit 1; }
	@command -v jq >/dev/null 2>&1 || { echo "❌ jq not found. Install: brew install jq"; exit 1; }
	@echo "✅ All prerequisites found."

fmt:  ## Format code with ruff
	uv run ruff format .

lint:  ## Lint code with ruff
	uv run ruff check .

type:  ## Type-check with mypy
	uv run mypy

test:  ## Run unit tests with coverage
	uv run pytest --cov=access_iq

test-integration:  ## Run integration tests against live AWS (requires deployed stacks)
	uv run pytest -m integration --no-header -v

ci: fmt lint type test  ## Run full CI pipeline

# ── Data profiling (requires live S3 session) ──────────────────────────
profile:  ## Run Bronze data profiling + generate data dictionary (requires make up + make ingest)
	uv run --package access-iq-ingestion --extra profiling python -m access_iq.profiling.profile_bronze

ready:  ## Run Bronze-to-Silver readiness gate (requires make up + make ingest)
	uv run --package access-iq-ingestion --extra profiling python -m access_iq.profiling.readiness_gate

dq-gate:  ## Run GE validation gate on Silver tables (requires make up + tunnel)
	eval $$(./scripts/tunnel.sh env) && uv run --package access-iq-flows python dbt/scripts/run_ge_gate.py

# ── Infrastructure (CDK) ────────────────────────────────────────────
# TRUST_VPC_ID is required for NetworkStack (peering). Get it from Trust CFN outputs or `make status`.
# Example: make infra-deploy TRUST_VPC_ID=vpc-0abc123
AWS_PROFILE := $(PLATFORM_PROFILE)
CDK_CONTEXT := -c "env=$${CDK_ENV:-dev}" $(if $(TRUST_VPC_ID),-c "trust_vpc_id=$(TRUST_VPC_ID)") $(if $(PLATFORM_PROFILE),--profile $(PLATFORM_PROFILE))

infra-bootstrap:  ## Bootstrap CDK (requires PLATFORM_PROFILE, CDK_ENV)
	@test -n "$${PLATFORM_PROFILE}" || { echo "ERROR: PLATFORM_PROFILE is not set. Export it: export PLATFORM_PROFILE=<your-platform-profile>"; exit 1; }
	cd infra && uv run cdk bootstrap $(CDK_CONTEXT)

infra-diff:  ## Show CDK diff
	cd infra && uv run cdk diff $(CDK_CONTEXT)

CDK_DEPLOY_TARGET := $(if $(CDK_STACK),$(CDK_STACK),--all)

infra-deploy:  ## Deploy CDK stacks (optional CDK_STACK=<name>, TRUST_VPC_ID=vpc-xxx)
	cd infra && uv run cdk deploy $(CDK_DEPLOY_TARGET) $(CDK_CONTEXT) --require-approval never

infra-destroy:  ## Destroy CDK stacks
	cd infra && uv run cdk destroy --all --force $(CDK_CONTEXT)

# ── Session orchestration ───────────────────────────────────────────
up:  ## Deploy Trust + Platform stacks (SKIP_GENERATE=1 reuse data, SKIP_SEED=1 infra only, SKIP_INFRA=1 reuse stacks)
	./scripts/session.sh up $(if $(SKIP_GENERATE),--skip-generate) $(if $(SKIP_SEED),--skip-seed) $(if $(SKIP_INFRA),--skip-infra)

down:  ## Destroy all stacks
	./scripts/session.sh down

status:  ## Show current stack states
	./scripts/session.sh status

ingest:  ## Run Bronze ingestion on ECS Fargate (3 parallel tasks)
	./scripts/session.sh ingest

pipeline:  ## Trigger full Prefect pipeline flow run (Bronze -> Silver -> GE -> Gold -> Export)
	./scripts/session.sh pipeline

dbt:  ## Run dbt command (e.g., make dbt CMD="run --select silver")
	eval $$(./scripts/tunnel.sh env) && cd dbt && uv run dbt $(CMD) --profiles-dir .

# ── Redshift tunnel ────────────────────────────────────────────────
rs-tunnel:  ## Start SSM port-forwarding tunnel to Redshift only (localhost:5439, foreground)
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
		echo "No .tunnel.pid file - tunnel not managed by make up"; \
	fi

tunnel-env:  ## Print export commands for dbt Redshift credentials
	@./scripts/tunnel.sh env

dashboard:  ## Run Streamlit dashboard locally (reads from S3 if secrets.toml is configured)
	cd dashboard && uv run streamlit run app.py

reconnect:  ## Re-establish SSM tunnels to Redshift + Prefect after session timeout
	./scripts/tunnel.sh reconnect
