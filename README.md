---
title: Spotify Manager
emoji: 🎧
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Personal Spotify library manager web UI
---

# Spotify Manager

A small mobile-first web UI over the Spotify Manager FastAPI backend, so the
library lookups and maintenance commands are usable from a phone.

This Space runs the app defined in `spotify_manager/web.py` (the pure API lives
in `spotify_manager/api.py`). It is protected by a shared password and talks to
Spotify with a pre-seeded OAuth token.

See **DEPLOY.md** for full setup: required secrets, how to generate the token
cache, and security notes.

## Local setup

Install [uv](https://docs.astral.sh/uv/) and
[just](https://just.systems/), then sync the locked environment:

```console
just install
```

The CLI reads Spotify credentials and application settings from `.env`. See
the secrets table below for the required names. The three queue playlist
settings are additionally required by `review-artists`.

Optional Spotify applications are configured as `APP5_CLIENT_ID` plus
`APP5_CLIENT_SECRET`, through the matching `APP8_*` names. Requests start with
the primary `SPOTIPY_*` app and rotate through `app5`, `app6`, `app7`, and
`app8` whenever Spotify returns HTTP 429. The selected app's access token is
force-refreshed before the failed request is retried.

Run `just` or `just --list` to see every recipe. Each Typer command has a
same-named recipe, and arguments are forwarded unchanged:

```console
uv run spotify-manager COMMAND [ARGS]
just COMMAND [ARGS]
```

For example, these two calls are equivalent, including quoted values:

```console
uv run spotify-manager album-decision "Kind of Blue" --artist "Miles Davis"
just album-decision "Kind of Blue" --artist "Miles Davis"
```

Use `--help` through either interface to see the authoritative options for a
command, for example `just review-artists --help`.

## Library mirror commands

The library mirror is built through two deliberately separate commands.

### `analyse-library-async`

Reads only `spotify_manager/files/YourLibrary.json` and writes
`albums_total_new_async.json`, `liked_tracks_total_async.json`,
`artists_total_async.json`, and `stats_history_async.json`.

```console
uv run spotify-manager analyse-library-async
just analyse-library-async
```

### `analyse-library-sync`

Reads only the live Spotify API and writes the matching `*_sync.json` files.
It checkpoints every page, reconciles additions made while the scan is running,
and retries Spotify 5xx responses with capped exponential backoff.

```console
uv run spotify-manager analyse-library-sync
just analyse-library-sync
```

During a CLI 5xx retry wait, press `r` to refresh and switch to the next Spotify
credential set and retry immediately, or `q` to stop cleanly. Rerunning the
command resumes from its checkpoint. Both analysis modes keep JSON-lines audit
logs and an undo manifest under `spotify_manager/files/`.

### `restore-library-sync`

Restore the generated files from a completed analysis by passing the run id
printed in its summary. Omit `--yes` to confirm interactively:

```console
uv run spotify-manager restore-library-sync RUN_ID --yes
just restore-library-sync RUN_ID --yes
```

The same commands are available in the web UI. Their API endpoints return a
background job that can be polled or cancelled. The UI streams timestamped
progress, credential-rotation, retry, and error messages, and keeps the clean
cancel action available while a retry is waiting:

```text
POST /commands/analyse-library-async
POST /commands/analyse-library-sync
GET  /commands/library-analysis-jobs
GET  /commands/library-analysis-jobs/{job_id}
POST /commands/library-analysis-jobs/{job_id}/cancel
```

After a web-page reload, the UI reconnects to active jobs through the collection
endpoint, restores their progress and logs, and resumes polling automatically.

## Library maintenance commands

### `monthly-routines`

Runs the complete monthly workflow: compare the exported and tracked album
lists, reconcile `albums_total.json` against Spotify, process the previous
control-file results, update statistics, and create the next monthly playlist.

```console
uv run spotify-manager monthly-routines
just monthly-routines
```

### `update-total-albums`

Rebuilds `albums_total.json` from live saved albums. Use `--just-update` to
continue after the number of albums already stored instead of starting at
offset zero.

```console
uv run spotify-manager update-total-albums --just-update
just update-total-albums --just-update
```

### `compare-lib-files`

Compares album ids in `YourLibrary.json` and `albums_total.json`, then writes
the additions and removals to `comparison.json`. This command only reads local
files.

```console
uv run spotify-manager compare-lib-files
just compare-lib-files
```

### `analyse-comp`

Reads `comparison.json`, checks each proposed change against the live Spotify
library, and prints whether the album is currently saved. It does not modify
the live library.

```console
uv run spotify-manager analyse-comp
just analyse-comp
```

### `convert-lib`

Reconciles `albums_total.json` using `comparison.json`, confirming each change
against the live Spotify library before adding or removing the local entry.

```console
uv run spotify-manager convert-lib
just convert-lib
```

### `restore-your-library`

Restores artists and liked tracks found in `YourLibrary.json` but missing from
the live Spotify library. This mutates the Spotify account.

```console
uv run spotify-manager restore-your-library
just restore-your-library
```

### `count-artists`

Prints the number of artists in `YourLibrary.json`; no Spotify request is made.

```console
uv run spotify-manager count-artists
just count-artists
```

### `refresh-spotify-tokens`

Authenticates or force-refreshes every configured Spotify application. Run
this locally before deploying multi-app rotation to create one OAuth cache per
app. A browser login is requested for any app that does not have a cache yet.

```console
uv run spotify-manager refresh-spotify-tokens
just refresh-spotify-tokens
```

The conventional cache files are
`spotify_manager/auth/spotipy_token_cache.json` and
`spotipy_token_cache_app5.json` through `spotipy_token_cache_app8.json` in the
same directory. They are ignored by Git and Docker.

## Review commands

### `artist-stats`

Prints local liked-track and saved-release counts. Identify the artist by
exported name or Spotify id:

```console
uv run spotify-manager artist-stats "Miles Davis"
just artist-stats "Miles Davis"

uv run spotify-manager artist-stats --artist-id SPOTIFY_ARTIST_ID
just artist-stats --artist-id SPOTIFY_ARTIST_ID
```

### `album-decision`

Evaluates whether an album meets the liked-track threshold. Use an exported
name or `--album-id`; `--artist` disambiguates duplicate album names.
`--no-cache` bypasses the local tracklist cache, while `--refresh-cache`
re-fetches and updates it.

```console
uv run spotify-manager album-decision "Kind of Blue" --artist "Miles Davis" --threshold 0.5
just album-decision "Kind of Blue" --artist "Miles Davis" --threshold 0.5
```

### `review-album-limits`

Interactively reviews albums below the keep threshold and removes approved
candidates from Spotify and `albums_total_new.json`. Decisions and removals are
logged and resumable. Zero-liked albums are removed automatically after a live
liked-track check.

```console
uv run spotify-manager review-album-limits --threshold 0.5
just review-album-limits --threshold 0.5
```

The command also accepts `--no-cache` and `--refresh-cache`.

### `recover-removed-albums`

Audits the removal log for additional credited artists and future-dated
releases. It follows missing credited artists and restores future releases.
Start with `--dry-run`; use `--limit` to process a small batch.

```console
uv run spotify-manager recover-removed-albums --dry-run --limit 25
just recover-removed-albums --dry-run --limit 25
```

### `review-artists`

Reviews `artists_total.json`, unfollows eligible zero-liked artists, and places
a selected track in the configured queue tier without moving artists that
should remain in an existing tier. The workflow is logged and resumable.

```console
uv run spotify-manager review-artists --limit 25
just review-artists --limit 25
```

Use `--refresh-cache` to discard cached catalog candidates before reviewing.

## Development recipes

| Recipe | Purpose |
| --- | --- |
| `just install` | Sync `.venv` from `uv.lock`. |
| `just format` | Format the package and apply Ruff fixes. |
| `just lint` | Run Ruff lint and formatting checks. |
| `just lint-ruff` | Run only the Ruff linter. |
| `just lint-ruff-format` | Run only the Ruff formatting check. |
| `just lint-mypy` | Type-check the package. |
| `just lint-audit` | Audit dependencies with `pip-audit`. |
| `just test` | Run lint plus the randomized test suite with coverage. |
| `just ci-test` | Run lint and tests with a JUnit report. Set `PYTEST_REPORT_PATH` to override `test_report.xml`. |
| `just clean` | Remove build, bytecode, test, and coverage artifacts. |
| `just clean-build` | Remove package build artifacts. |
| `just clean-pyc` | Remove Python bytecode and editor backup files. |
| `just clean-test` | Remove pytest and coverage artifacts. |

## Required Space secrets

| Secret | Purpose |
| --- | --- |
| `APP_PASSWORD` | Shared password for the web UI / API. |
| `SPOTIPY_CLIENT_ID` | Spotify app client id. |
| `SPOTIPY_CLIENT_SECRET` | Spotify app client secret. |
| `SPOTIPY_REDIRECT_URI` | Spotify app redirect URI. Use an explicit loopback IP for local auth, e.g. `http://127.0.0.1:8080/callback`; it must match your Spotify dashboard. |
| `SPOTIPY_CACHE_JSON` | Contents of your local `spotify_manager/auth/spotipy_token_cache.json` token file (enables headless auth). |
| `APP5_CLIENT_ID` ... `APP8_CLIENT_ID` | Client ids for the additional Spotify apps. Each configured id requires its matching secret. |
| `APP5_CLIENT_SECRET` ... `APP8_CLIENT_SECRET` | Client secrets for the additional Spotify apps. |
| `APP5_SPOTIPY_CACHE_JSON` ... `APP8_SPOTIPY_CACHE_JSON` | Contents of each matching local `spotipy_token_cache_appN.json`, required for headless rotation. |
| `ALBUMS_TO_ADD` | App setting (integer). |
| `LIMIT` | App setting (integer). |
| `THE_QUEUE_PLAYLIST` | Spotify URL or id for the 1-5 liked-track queue. |
| `THE_QUEUE_2_PLAYLIST` | Spotify URL or id for the 6-17 liked-track queue. |
| `THE_QUEUE_3_PLAYLIST` | Spotify URL or id for the 18+ liked-track queue. |

> This Space should be **Private** — the repository contains your personal
> library export files.
