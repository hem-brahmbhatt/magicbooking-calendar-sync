.DEFAULT_GOAL := help

AWS_PROFILE ?= hemtech
AWS_REGION  ?= eu-west-2
ALERT_EMAIL ?= hamant.brahmbhatt@hemtech.io
FUNCTION    := magicbooking-calendar-sync
LOG_GROUP   := /aws/lambda/$(FUNCTION)

.PHONY: help install test build tf-init tf-fmt tf-validate tf-plan deploy destroy secrets invoke logs clean

help: ## Show this help
	@echo "magicbooking-calendar-sync"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Variables (override with VAR=value): AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=$(AWS_REGION) ALERT_EMAIL=$(ALERT_EMAIL)"

install: ## Create .venv and install the package + dev/test dependencies
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test: ## Run the full test suite
	.venv/bin/python -m pytest -v

build: ## Build the Lambda deployment package into build/ (Docker-verified import smoke test)
	./scripts/build_lambda.sh

tf-init: ## Initialize Terraform providers
	cd infra && terraform init

tf-fmt: ## Check Terraform formatting
	cd infra && terraform fmt -check

tf-validate: ## Validate the Terraform configuration
	cd infra && terraform validate

tf-plan: build ## Build the Lambda package, then show what `terraform apply` would change
	cd infra && eval "$$(aws configure export-credentials --profile $(AWS_PROFILE) --format env)" && \
		terraform plan -var="alert_email=$(ALERT_EMAIL)"

deploy: build ## Build the Lambda package and apply Terraform (creates/updates real AWS infra)
	cd infra && eval "$$(aws configure export-credentials --profile $(AWS_PROFILE) --format env)" && \
		terraform apply -var="alert_email=$(ALERT_EMAIL)"

destroy: ## Tear down all AWS infrastructure for this project (asks for interactive confirmation)
	cd infra && eval "$$(aws configure export-credentials --profile $(AWS_PROFILE) --format env)" && \
		terraform destroy -var="alert_email=$(ALERT_EMAIL)"

secrets: ## Push current .env values into SSM Parameter Store (values are never printed)
	@set -a; . ./.env; set +a; \
	aws ssm put-parameter --profile $(AWS_PROFILE) --region $(AWS_REGION) --name /magicbooking-calendar-sync/magicbooking/username --type SecureString --overwrite --value "$$MAGICBOOKING_USERNAME" >/dev/null && echo "magicbooking/username: updated"; \
	aws ssm put-parameter --profile $(AWS_PROFILE) --region $(AWS_REGION) --name /magicbooking-calendar-sync/magicbooking/password --type SecureString --overwrite --value "$$MAGICBOOKING_PASSWORD" >/dev/null && echo "magicbooking/password: updated"; \
	aws ssm put-parameter --profile $(AWS_PROFILE) --region $(AWS_REGION) --name /magicbooking-calendar-sync/google/oauth_client_id --type SecureString --overwrite --value "$$GOOGLE_OAUTH_CLIENT_ID" >/dev/null && echo "google/oauth_client_id: updated"; \
	aws ssm put-parameter --profile $(AWS_PROFILE) --region $(AWS_REGION) --name /magicbooking-calendar-sync/google/oauth_client_secret --type SecureString --overwrite --value "$$GOOGLE_OAUTH_CLIENT_SECRET" >/dev/null && echo "google/oauth_client_secret: updated"; \
	aws ssm put-parameter --profile $(AWS_PROFILE) --region $(AWS_REGION) --name /magicbooking-calendar-sync/google/oauth_refresh_token --type SecureString --overwrite --value "$$GOOGLE_OAUTH_REFRESH_TOKEN" >/dev/null && echo "google/oauth_refresh_token: updated"; \
	aws ssm put-parameter --profile $(AWS_PROFILE) --region $(AWS_REGION) --name /magicbooking-calendar-sync/google/calendar_id --type SecureString --overwrite --value "$$GOOGLE_CALENDAR_ID" >/dev/null && echo "google/calendar_id: updated"

invoke: ## Manually trigger one real sync run against the deployed Lambda
	aws lambda invoke --profile $(AWS_PROFILE) --region $(AWS_REGION) \
		--function-name $(FUNCTION) --cli-read-timeout 90 /tmp/$(FUNCTION)-invoke-out.json
	@cat /tmp/$(FUNCTION)-invoke-out.json
	@echo

logs: ## Tail the last 10 minutes of CloudWatch logs for the deployed Lambda
	aws logs tail $(LOG_GROUP) --profile $(AWS_PROFILE) --region $(AWS_REGION) --since 10m --follow

clean: ## Remove local build artifacts (build/, infra/lambda.zip, pytest cache)
	rm -rf build infra/lambda.zip .pytest_cache
