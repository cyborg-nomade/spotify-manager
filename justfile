set positional-arguments

package_path := "spotify_manager"
check_path := package_path
pytest_report_path := env("PYTEST_REPORT_PATH", "test_report.xml")
cli := "uv run spotify-manager"

alias help := default
alias ci_test := ci-test

# List the available recipes.
default:
    @just --list

# Sync the virtual environment from uv.lock.
install:
    uv sync

# Remove all build, bytecode, test, and coverage artifacts.
clean: clean-build clean-pyc clean-test

# Remove Python build artifacts.
clean-build:
    rm -rf build/ dist/ .eggs/
    find . -name '*.egg-info' -exec rm -rf {} +
    find . -name '*.egg' -exec rm -f {} +

# Remove Python bytecode and editor backup files.
clean-pyc:
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '*~' -exec rm -f {} +
    find . -name '__pycache__' -exec rm -rf {} +

# Remove pytest and coverage artifacts.
clean-test:
    rm -f .coverage
    rm -rf htmlcov/

# Format the package and fix Ruff lint/import issues.
format:
    uv run ruff format {{ check_path }}
    uv run ruff check --fix {{ check_path }}

# Run the Ruff lint and formatting checks.
lint: lint-ruff lint-ruff-format

# Check the package with Ruff.
lint-ruff:
    uv run ruff check {{ check_path }}

# Check package formatting with Ruff.
lint-ruff-format:
    uv run ruff format --check {{ check_path }}

# Type-check the package with mypy.
lint-mypy:
    uv run mypy --config-file=pyproject.toml {{ check_path }}

# Audit installed dependencies for known vulnerabilities.
lint-audit:
    uv run pip-audit

# Run lint and the randomized test suite with coverage.
test: lint
    uv run pytest --random-order --show-capture=no --cov-report term-missing --cov={{ package_path }} tests

# Run lint and tests with a JUnit report for CI.
ci-test: lint
    uv run pytest --junitxml={{ quote(pytest_report_path) }} --random-order --show-capture=no --cov-report term-missing --cov={{ package_path }} tests

# Run the monthly comparison, reconciliation, stats, and playlist routine.
monthly-routines *args:
    {{ cli }} monthly-routines "$@"

# Rebuild or continue the saved-album list from Spotify.
update-total-albums *args:
    {{ cli }} update-total-albums "$@"

# Restore exported artists and tracks to the live Spotify library.
restore-your-library *args:
    {{ cli }} restore-your-library "$@"

# Compare YourLibrary.json albums with albums_total.json.
compare-lib-files *args:
    {{ cli }} compare-lib-files "$@"

# Check comparison.json entries against the live Spotify library.
analyse-comp *args:
    {{ cli }} analyse-comp "$@"

# Reconcile albums_total.json using comparison.json and Spotify.
convert-lib *args:
    {{ cli }} convert-lib "$@"

# Count artists in YourLibrary.json.
count-artists *args:
    {{ cli }} count-artists "$@"

# Authenticate or force-refresh every configured Spotify app token.
refresh-spotify-tokens *args:
    {{ cli }} refresh-spotify-tokens "$@"

# Build *_async.json mirrors only from YourLibrary.json.
analyse-library-async *args:
    {{ cli }} analyse-library-async "$@"

# Build *_sync.json mirrors only from the live Spotify API.
analyse-library-sync *args:
    {{ cli }} analyse-library-sync "$@"

# Restore generated mirror files from an analysis backup.
restore-library-sync *args:
    {{ cli }} restore-library-sync "$@"

# Show local liked-track and saved-release counts for an artist.
artist-stats *args:
    {{ cli }} artist-stats "$@"

# Evaluate an album against the liked-track keep threshold.
album-decision *args:
    {{ cli }} album-decision "$@"

# Interactively review and remove albums below the keep threshold.
review-album-limits *args:
    {{ cli }} review-album-limits "$@"

# Audit removed albums and restore future releases.
recover-removed-albums *args:
    {{ cli }} recover-removed-albums "$@"

# Review followed artists and manage their queue placement.
review-artists *args:
    {{ cli }} review-artists "$@"
