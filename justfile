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

# Verify pure policies without application fixtures, configuration, or SDKs.
test-domain:
    uv run ruff check spotify_manager/domain tests/domain
    uv run ruff format --check spotify_manager/domain tests/domain
    uv run mypy --strict spotify_manager/domain tests/domain
    uv run pytest --confcutdir=tests/domain --cov=spotify_manager.domain --cov-branch --cov-fail-under=100 tests/domain

# Verify complete injected use cases without application fixtures or SDK startup.
test-application:
    uv run ruff check spotify_manager/application tests/application
    uv run ruff format --check spotify_manager/application tests/application
    uv run mypy --strict spotify_manager/application tests/application
    uv run pytest --confcutdir=tests/application \
        --cov=spotify_manager.application.found_art_values \
        --cov=spotify_manager.application.recommendation_seeds \
        --cov=spotify_manager.application.recommendation_candidates \
        --cov=spotify_manager.application.recommendation_resolution \
        --cov=spotify_manager.application.recommendation_run \
        --cov=spotify_manager.application.album_recommendations \
        --cov=spotify_manager.application.sauvignon_values \
        --cov=spotify_manager.application.sauvignon_selection \
        --cov=spotify_manager.application.sauvignon_run \
        --cov=spotify_manager.application.dormant_values \
        --cov=spotify_manager.application.dormant_tracks \
        --cov=spotify_manager.application.dormant_recovery \
        --cov=spotify_manager.application.artist_mapping \
        --cov=spotify_manager.application.future_release \
        --cov=spotify_manager.application.release_check_values \
        --cov=spotify_manager.application.release_opening \
        --cov=spotify_manager.application.genre_run \
        --cov=spotify_manager.application.queue_seeds \
        --cov=spotify_manager.application.queue_recommendations \
        --cov=spotify_manager.application.queue_fill \
        --cov=spotify_manager.application.queue_fill_candidates \
        --cov=spotify_manager.application.queue_fill_values \
        --cov=spotify_manager.application.queue_flush \
        --cov=spotify_manager.application.queue_flush_execution \
        --cov=spotify_manager.application.queue_flush_values \
        --cov=spotify_manager.application.queue_flush_planning \
        --cov=spotify_manager.application.something_old_run \
        --cov=spotify_manager.application.something_old_values \
        --cov=spotify_manager.application.golden_selection \
        --cov=spotify_manager.application.palace_values \
        --cov=spotify_manager.application.palace_run \
        --cov=spotify_manager.application.palace_planning \
        --cov=spotify_manager.application.palace_history \
        --cov=spotify_manager.application.palace_mirror \
        --cov=spotify_manager.application.palace_cursor \
        --cov=spotify_manager.application.discography_values \
        --cov=spotify_manager.application.discography_planning \
        --cov=spotify_manager.application.discography_execution \
        --cov=spotify_manager.application.discography_history \
        --cov=spotify_manager.application.discography_catalog \
        --cov=spotify_manager.application.discography_queues \
        --cov=spotify_manager.application.new_year_values \
        --cov=spotify_manager.application.new_year_effects \
        --cov=spotify_manager.application.new_year_run \
        --cov=spotify_manager.application.new_year_execution \
        --cov=spotify_manager.application.new_year_planning \
        --cov=spotify_manager.application.new_year_resolution \
        --cov=spotify_manager.application.new_year_sources \
        --cov=spotify_manager.application.new_year_charts \
        --cov=spotify_manager.application.new_year_membership \
        --cov=spotify_manager.application.new_year_retry \
        --cov=spotify_manager.application.artist_review_values \
        --cov=spotify_manager.application.artist_review_effects \
        --cov=spotify_manager.application.artist_review_session \
        --cov=spotify_manager.application.artist_review_recovery \
        --cov=spotify_manager.application.artist_review_decisions \
        --cov=spotify_manager.application.artist_review_run \
        --cov=spotify_manager.application.artist_review_catalog \
        --cov=spotify_manager.application.artist_review_membership \
        --cov=spotify_manager.application.artist_review_state \
        --cov=spotify_manager.application.legacy_library_control \
        --cov=spotify_manager.application.legacy_library_conversion \
        --cov=spotify_manager.application.legacy_library_effects \
        --cov=spotify_manager.application.legacy_library_monthly \
        --cov=spotify_manager.application.legacy_library_refresh \
        --cov=spotify_manager.application.library_analysis_artists \
        --cov=spotify_manager.application.library_analysis_checkpoint \
        --cov=spotify_manager.application.library_analysis_effects \
        --cov=spotify_manager.application.library_analysis_export \
        --cov=spotify_manager.application.library_analysis_offsets \
        --cov=spotify_manager.application.library_analysis_publication \
        --cov=spotify_manager.application.library_analysis_records \
        --cov=spotify_manager.application.library_analysis_run \
        --cov=spotify_manager.application.library_analysis_values \
        --cov=spotify_manager.application.queue_values \
        --cov=spotify_manager.application.genre_progress \
        --cov=spotify_manager.application.genre_values \
        --cov=spotify_manager.application.release_run \
        --cov=spotify_manager.application.release_review \
        --cov=spotify_manager.application.release_results \
        --cov=spotify_manager.application.release_progress \
        --cov=spotify_manager.application.release_effects \
        --cov=spotify_manager.application.release_destinations \
        --cov=spotify_manager.application.release_artists \
        --cov=spotify_manager.application.historical_playlists \
        --cov=spotify_manager.application.historical_resolution \
        --cov=spotify_manager.application.historical_selection \
        --cov=spotify_manager.application.historical_values \
        --cov=spotify_manager.application.history_refresh \
        --cov=spotify_manager.application.history_values \
        --cov=spotify_manager.application.album_review \
        --cov=spotify_manager.application.album_limits \
        --cov=spotify_manager.application.album_recovery \
        --cov=spotify_manager.application.artist_follows \
        --cov=spotify_manager.application.artist_assessment \
        --cov=spotify_manager.application.new_kids_values \
        --cov=spotify_manager.application.new_kids_state \
        --cov=spotify_manager.application.new_kids_planner \
        --cov=spotify_manager.application.discovery_observations \
        --cov=spotify_manager.application.discovery_library \
        --cov=spotify_manager.application.discovery_completion \
        --cov=spotify_manager.application.discovery_destinations \
        --cov=spotify_manager.application.discovery_queue \
        --cov=spotify_manager.application.discovery_review \
        --cov=spotify_manager.application.discovery_run \
        --cov=spotify_manager.application.queue_2 \
        --cov=spotify_manager.application.queue_3_import \
        --cov=spotify_manager.application.queue_3_import_review \
        --cov=spotify_manager.application.queue_3_values \
        --cov=spotify_manager.application.queue_3_planner \
        --cov=spotify_manager.application.queue_3_composers \
        --cov=spotify_manager.application.queue_3_state \
        --cov=spotify_manager.application.queue_3_execution \
        --cov=spotify_manager.application.queue_3_run \
        --cov=spotify_manager.application.queue_3_review \
        --cov=spotify_manager.application.new_kids_execution \
        --cov=spotify_manager.application.release_history \
        --cov=spotify_manager.application.credited_artists \
        --cov=spotify_manager.application.composer_routes \
        --cov=spotify_manager.application.composer_progression \
        --cov=spotify_manager.application.library_statistics \
        --cov=spotify_manager.application.library_affinity \
        --cov=spotify_manager.application.new_wine_values \
        --cov=spotify_manager.application.new_wine \
        --cov=spotify_manager.application.new_wine_execution \
        --cov=spotify_manager.application.new_wine_observations \
        --cov=spotify_manager.application.new_wine_planner \
        --cov=spotify_manager.application.new_wine_plans \
        --cov=spotify_manager.application.new_wine_state \
        --cov=spotify_manager.application.release_evaluation \
        --cov=spotify_manager.application.wine_cellar \
        --cov=spotify_manager.application.recovery_values \
        --cov=spotify_manager.application.music \
        --cov=spotify_manager.application.requeue \
        --cov=spotify_manager.application.requeue_result \
        --cov=spotify_manager.application.slow_listening \
        --cov=spotify_manager.application.slow_listening_plan \
        --cov=spotify_manager.application.slow_listening_state \
        --cov=spotify_manager.application.slow_listening_values \
        --cov-branch --cov-fail-under=100 tests/application

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

# Print the complete shared state or one namespace.
state-show *args:
    {{ cli }} state-show "$@"

# Export the complete shared state to a JSON snapshot.
state-export *args:
    {{ cli }} state-export "$@"

# Validate and apply a manually edited state snapshot.
state-edit *args:
    {{ cli }} state-edit "$@"

# Show durable canonical-file versions and local synchronization.
library-data-status *args:
    {{ cli }} library-data-status "$@"

# Hydrate canonical files from the shared Hugging Face dataset.
library-data-pull *args:
    {{ cli }} library-data-pull "$@"

# Publish canonical files to the shared Hugging Face dataset.
library-data-push *args:
    {{ cli }} library-data-push "$@"

# Upload refreshed Spotify and Last.fm exports to the HF Space.
upload-library-files-to-hf *args:
    {{ cli }} upload-library-files-to-hf "$@"

# Select Friday-routine tracks from past Last.fm scrobbles.
blast-from-the-past *args:
    {{ cli }} blast-from-the-past "$@"

# Add popular liked tracks from artists absent in the current year.
blast-from-the-past-artists *args:
    {{ cli }} blast-from-the-past-artists "$@"

# Rebuild Last.fm-style unheard recommendations for Found Art.
found-art *args:
    {{ cli }} found-art "$@"

# Recommend unheard albums and add their first tracks to Sauvignon.
fill-sauvignon-from-lastfm *args:
    {{ cli }} fill-sauvignon-from-lastfm "$@"

# Recommend unheard Last.fm artists and add one marker each to The Queue.
fill-queue-from-lastfm *args:
    {{ cli }} fill-queue-from-lastfm "$@"

# Merge the latest Last.fm API scrobbles into the canonical export.
update-scrobble-history *args:
    {{ cli }} update-scrobble-history "$@"

# Fill an empty Something Old slot from Last.fm Golden Oldies.
something-old *args:
    {{ cli }} something-old "$@"

# Check 100+ scrobble artists for releases feeding Wine Cellar and New Vintage.
check-new-releases *args:
    {{ cli }} check-new-releases "$@"

# Advance every New Wine track once by its selected release.
flush-new-wine *args:
    {{ cli }} flush-new-wine "$@"

# Advance every New Kids artist once and refill it from Queue 2.
flush-new-kids *args:
    {{ cli }} flush-new-kids "$@"

# Advance the first ten artists in The Queue through their unliked top tracks.
flush-queue *args:
    {{ cli }} flush-queue "$@"

# Fill New Kids, then advance the first ten remaining Queue 2 artists.
flush-queue-2 *args:
    {{ cli }} flush-queue-2 "$@"

# Import last year's discoveries, then advance the first ten Queue 3 artists.
flush-queue-3 *args:
    {{ cli }} flush-queue-3 "$@"

# Import last year's Great Discoveries without advancing Queue 3.
import-queue-3-previous-year *args:
    {{ cli }} import-queue-3-previous-year "$@"

# Advance the first two Slow Listening tracks through studio releases.
flush-slow-listening *args:
    {{ cli }} flush-slow-listening "$@"

# Advance the first Requeue for a Dream artist to their next release.
flush-requeue-for-a-dream *args:
    {{ cli }} flush-requeue-for-a-dream "$@"

# Plan a round-week batch from the three ordered discography queues.
plan-discographies *args:
    {{ cli }} plan-discographies "$@"

# Add five alphabetical and five historical albums to Palace of Memory.
fill-palace-of-memory *args:
    {{ cli }} fill-palace-of-memory "$@"

# Add tracks from today's Last.fm anniversaries to Daily Mind Radio.
daily-mind-radio *args:
    {{ cli }} daily-mind-radio "$@"

# Save and sample the first unchecked Every Noise genre playlist.
genre-reveal *args:
    {{ cli }} genre-reveal "$@"

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

# Show live liked-track and saved-release counts for an artist.
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

# Preview or apply the complete previous-year retrospective.
new-year *args:
    {{ cli }} new-year "$@"
