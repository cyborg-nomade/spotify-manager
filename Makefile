PACKAGE_NAME = spotify-manager
PACKAGE_PATH = .
PYTEST_REPORT_PATH = ${PYTEST_REPORT_PATH:test_report.xml}

CHECK_PATH   = $(PACKAGE_PATH)

# Add the following 'help' target to your Makefile
# And add help text after each target name starting with '\#\#'
.PHONY: help
help: ## This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

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


.PHONY: black
black: ## Format codebase
	black $(CHECK_PATH)


.PHONY: isort
isort: ## Format imports in the codebase
	isort $(CHECK_PATH)

.PHONY: format
format: black isort ## Format the codebase according to our standards


.PHONY: lint
lint: lint-flake8 lint-isort lint-black ## check style with flake8


.PHONY: lint-black
lint-black: ## validate black formating
	black --check --diff $(CHECK_PATH)


.PHONY: lint-flake8
lint-flake8: ## validate using flake8
	flake8 $(CHECK_PATH)


.PHONY: lint-isort
lint-isort: ## validate using isort
	isort --check-only $(CHECK_PATH)


.PHONY: lint-mypy
lint-mypy: ## validate using mypy
	mypy --config-file=pyproject.toml $(CHECK_PATH)

.PHONY: lint-bandit
lint-bandit: ## validate using bandit
	bandit -r $(CHECK_PATH) -c "pyproject.toml"


.PHONY: lint-pip-audit
lint-audit: ## validate using pip-audit
	pip-audit


.PHONY: test
test: lint ## run tests in a random order with the default Python
	python -m pytest --random-order --show-capture=no --cov-report term-missing --cov=$(PACKAGE_PATH) tests


.PHONY: ci_test
ci_test: lint ## run tests in a random order with the default Python, in CI env
	python -m pytest --junitxml=$(PYTEST_REPORT_PATH) --random-order --show-capture=no --cov-report term-missing --cov=$(PACKAGE_PATH) tests
