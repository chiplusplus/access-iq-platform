.PHONY: setup fmt fmt-check lint type test ci infra-bootstrap infra-diff infra-deploy infra-destroy

setup:
	uv sync --all-packages
	uv run pre-commit install

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

type:
	uv run mypy .

test:
	uv run pytest --cov=access_iq

ci: fmt-check lint type test

infra-bootstrap:
	cd infra && AWS_PROFILE=$(AWS_PROFILE) uv run cdk bootstrap -c env=$(CDK_ENV)

infra-diff:
	cd infra && AWS_PROFILE=$(AWS_PROFILE) uv run cdk diff -c env=$(CDK_ENV)

infra-deploy:
	cd infra && AWS_PROFILE=$(AWS_PROFILE) uv run cdk deploy $(CDK_STACK) --require-approval never -c env=$(CDK_ENV)

infra-destroy:
	cd infra && AWS_PROFILE=$(AWS_PROFILE) uv run cdk destroy --force -c env=$(CDK_ENV)
