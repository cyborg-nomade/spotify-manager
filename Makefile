PACKAGE_NAME = spotify-manager
PACKAGE_PATH = spotify_manager
PYTEST_REPORT_PATH = ${PYTEST_REPORT_PATH:test_report.xml}

CHECK_PATH   = $(PACKAGE_PATH)

# Add the following 'help' target to your Makefile
# And add help text after each target name starting with '\#\#'
.PHONY: help
help: ## This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Sync the virtual environment from the lockfile
	uv sync

.PHONY: clean
clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts


.PHONY: clean-build
clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +


.PHONY: clean-pyc
clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +


.PHONY: clean-test
clean-test: ## remove test and coverage artifacts
	rm -f .coverage
	rm -fr htmlcov/


.PHONY: format
format: ## Format the codebase and fix imports with ruff
	uv run ruff format $(CHECK_PATH)
	uv run ruff check --fix $(CHECK_PATH)


.PHONY: lint
lint: lint-ruff lint-ruff-format ## check style with ruff


.PHONY: lint-ruff
lint-ruff: ## validate using ruff linter
	uv run ruff check $(CHECK_PATH)


.PHONY: lint-ruff-format
lint-ruff-format: ## validate formatting using ruff
	uv run ruff format --check $(CHECK_PATH)


.PHONY: lint-mypy
lint-mypy: ## validate using mypy
	uv run mypy --config-file=pyproject.toml $(CHECK_PATH)


.PHONY: lint-pip-audit
lint-audit: ## validate using pip-audit
	uv run pip-audit


.PHONY: test
test: lint ## run tests in a random order with the default Python
	uv run pytest --random-order --show-capture=no --cov-report term-missing --cov=$(PACKAGE_PATH) tests


.PHONY: ci_test
ci_test: lint ## run tests in a random order with the default Python, in CI env
	uv run pytest --junitxml=$(PYTEST_REPORT_PATH) --random-order --show-capture=no --cov-report term-missing --cov=$(PACKAGE_PATH) tests