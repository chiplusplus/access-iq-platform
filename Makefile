.PHONY: setup install fmt lint type test ci infra-bootstrap infra-diff infra-deploy infra-destroy

ENV= . .venv/bin/activate
setup:
	uv venv
	$(ENV) && uv pip install -e ".[dev]"
	$(ENV) && pre-commit install

install:
	$(ENV) && uv pip install -r pyproject.toml --all-extras

fmt:
	$(ENV) && ruff format .

lint:
	$(ENV) && ruff check .

type:
	$(ENV) && mypy .

test:
	$(ENV) && pytest --cov=access_iq

ci: fmt lint type test

infra-bootstrap:
	$(ENV) && cd infra && AWS_PROFILE=$(AWS_PROFILE) cdk bootstrap -c env=$(CDK_ENV)

infra-diff:
	$(ENV) && cd infra && AWS_PROFILE=$(AWS_PROFILE) cdk diff -c env=$(CDK_ENV)

infra-deploy:
	$(ENV) && cd infra && AWS_PROFILE=$(AWS_PROFILE) cdk deploy --require-approval never -c env=$(CDK_ENV)

infra-destroy:
	$(ENV) && cd infra && AWS_PROFILE=$(AWS_PROFILE) cdk destroy --force -c env=$(CDK_ENV)
