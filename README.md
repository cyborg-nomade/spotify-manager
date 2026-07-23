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

## Genre Reveal

The web UI includes a **Genre reveal** launcher immediately below Daily Mind
Radio. It opens the existing 6,132-genre nearest-neighbour route through the
Every Noise map without changing its ordering or controls.

Set `GENRE_REVEAL_PLAYLIST` to the Spotify URL, URI, or ID of the destination
playlist. **Run next genre** opens the first incomplete genre and its main
Every Noise Spotify playlist, saves that playlist to the library, and appends
the first ten tracks that are not already in the configured destination. The
genre is checked only after both Spotify updates and the audit log succeed.

The same operation is available from the CLI. It opens both source pages by
default; pass `--no-open-pages` for a terminal-only run.

```console
uv run spotify-manager genre-reveal
just genre-reveal
just genre-reveal --no-open-pages
```

Completed genres and the **Hide completed** setting are synchronized through
the password-protected `/genre-reveal/state` API and cached in the browser as a
fallback. The browser retains the latest 50 snapshots, and the server backs up
the current file before every replacement. The server writes progress atomically to
`spotify_manager/files/genre_reveal_state.json`. This file survives page
reloads and can be shared across browsers while the Space container is
running, but it follows the same ephemeral-filesystem limitation as other
runtime files and is reset when an unpersisted HF container is replaced.
Set `GENRE_REVEAL_STATE_PATH` to a mounted persistent-storage path if the Space
has persistent storage enabled.

Successful Spotify operations are appended to
`spotify_manager/files/genre_reveal_log.jsonl`, including the source playlist
and exact track URIs added or skipped. Set `GENRE_REVEAL_LOG_PATH` to move this
audit log to persistent storage.

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

### `upload-library-files-to-hf`

Uploads refreshed source exports to the private
`cyborg-nomade/spotify-manager` Hugging Face Space. Authenticate once with
`hf auth login` before running it. By default, the command validates and
uploads both `YourLibrary.json` and `lastfmstats-man-et-arms.json`:

```console
uv run spotify-manager upload-library-files-to-hf
just upload-library-files-to-hf
```

Their update schedules differ, so either export can be uploaded independently:

```console
just upload-library-files-to-hf --your-library-only
just upload-library-files-to-hf --lastfm-only
```

Use `--dry-run` with any mode to validate the JSON and preview the files and
sizes without changing local files or HF. A Last.fm upload also regenerates the
tracked compressed base64 fallback parts, uploads them inline, and removes
obsolete parts from the Space. This keeps the Docker deployment usable when HF
stores the full export through large-file storage. A successful upload to
`main` triggers a Space rebuild.

### `blast-from-the-past`

Selects unique dates with scrobbles from
`spotify_manager/files/lastfmstats-man-et-arms.json`, between `2007-11-27` and
December 31 five years before the current year. Random.org chooses indexes into
the available-date list, and its UTC response timestamp determines the Last.fm
page, direction, and position according to section 6 of the music-listening
rules. Each selection is searched on Spotify and added to the playlist configured
by `BLAST_FROM_THE_PAST_PLAYLIST`.

Spotify candidates require an exact normalized artist match and at least 90%
track name similarity. When Last.fm supplies an album, unliked candidates also
require at least 90% album name similarity; liked tracks may override an album
mismatch. Recognized suffixes such as remaster, live, deluxe, and acoustic do
not reduce the score. If several results qualify, a currently liked track is
preferred. Existing playlist tracks and duplicate selections are not added.

```console
uv run spotify-manager blast-from-the-past
just blast-from-the-past

uv run spotify-manager blast-from-the-past --count 3
just blast-from-the-past --count 3

uv run spotify-manager blast-from-the-past --max-playlist-length 50
just blast-from-the-past --max-playlist-length 50
```

The default is `--count 10`. Use either `--count` or
`--max-playlist-length`, never both. Count mode processes that many random
dates; unavailable or non-matching tracks can therefore result in fewer Spotify
additions. Maximum-length mode processes the number of open slots found when the
command starts and never intentionally exceeds the requested cap.

The export timestamps are grouped into `Europe/Berlin` calendar dates, matching
the Last.fm date view, without omitting any scrobbles. Random.org must be
reachable; the command does not fall back to local pseudorandom selection.
The loader uses the adjacent compressed parts when the large JSON export is not
materialized correctly by a deployment platform's large-file storage.

The web UI exposes the same count and playlist-cap modes at the top of the page.
It runs the routine as a background job, streams its logs and match results, and
reconnects to an active run after a page reload:

```text
POST /commands/blast-from-the-past
GET  /commands/blast-from-the-past-jobs
GET  /commands/blast-from-the-past-jobs/{job_id}
```

### `found-art`

Builds a Last.fm-style recommendation list from the documented API and adds
unheard tracks to the playlist configured by `FOUND_ART_PLAYLIST`. Configure
`LASTFM_API_KEY` and `LASTFM_USERNAME`; the read-only API calls do not require a
Last.fm shared secret or user session.

The routine chooses a diverse mix of 90-day, one-year, and all-time seed tracks
from the Last.fm export, then combines the ranked results from
`track.getSimilar`. Both seed choice and final candidate choice use deterministic
weighted sampling keyed to the Friday that begins the listening week. Repeated
runs during one Friday-Thursday week therefore produce the same proposal, while
the next Friday rotates both the seeds and the candidate order.

A candidate is excluded when the normalized artist and track pair appears in
the export, the live API delta, or a previous successful Found Art run.
Remaster, deluxe, live, and similar edition suffixes are treated as the same
track. A completed batch contains at most one track per artist; a failed,
already-present, or liked candidate does not prevent another track by that
artist from being considered.

Before changing Spotify, candidates must pass the existing exact-artist and 90%
track-name matching rules. Liked Songs, existing playlist entries, and duplicate
Spotify results are not added. The default Friday-routine batch is 20 tracks:

```console
uv run spotify-manager found-art --dry-run
just found-art --dry-run

uv run spotify-manager found-art
just found-art

uv run spotify-manager found-art --count 10
just found-art --count 10

uv run spotify-manager found-art --max-playlist-length 50
just found-art --max-playlist-length 50
```

Use either `--count` or `--max-playlist-length`, never both. `--seed-count`
defaults to 30. Similar-track responses are cached for resumability during the
current listening week, saved after each seed, and refreshed after the Friday
boundary. Scrobbles newer than the export are kept in an append-only delta.
Every completed real or dry run is recorded in
`spotify_manager/files/found_art_log.jsonl`, including the week, seed sampling
keys, original candidate ranks, and weekly sampling keys.

The web UI places Found Art between Daily Mind Radio and Genre Reveal. Its count
control also defaults to 20, and the background job retains progress logs and
results so the page can reconnect after a reload:

```text
POST /commands/found-art?count=20
GET  /commands/found-art-jobs
GET  /commands/found-art-jobs/{job_id}
```

### `daily-mind-radio`

Selects one scrobble from today's date in the previous year, then from the
same calendar date at five-year intervals back through the earliest year in
the Last.fm export. In 2026, for example, the target years are 2025, 2020,
2015, and 2010; in 2028 they are 2027, 2022, 2017, 2012, and 2007. Dates with
no scrobbles are skipped.

One Random.org response timestamp determines the Last.fm page, direction, and
position for every populated anniversary date. The selected tracks use the
same Spotify matching, liked-track preference, album exception, and duplicate
handling as `blast-from-the-past`, and are added to the playlist configured by
`DAILY_MIND_RADIO_PLAYLIST`.

```console
uv run spotify-manager daily-mind-radio
just daily-mind-radio
```

On February 29, years without that date are skipped rather than substituted
with February 28. Random.org is not contacted when none of the anniversary
dates contains a scrobble.

The web UI provides the same routine directly below Blast from the Past. It
runs in the background, shows the anniversary dates, skips, match results, and
logs, and reconnects after a page reload:

```text
POST /commands/daily-mind-radio
GET  /commands/daily-mind-radio-jobs
GET  /commands/daily-mind-radio-jobs/{job_id}
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
| `BLAST_FROM_THE_PAST_PLAYLIST` | Spotify URL or id for Friday Routine recovery tracks. |
| `DAILY_MIND_RADIO_PLAYLIST` | Spotify URL or id for anniversary recovery tracks. |
| `GENRE_REVEAL_PLAYLIST` | Spotify URL or id that receives each genre playlist's first ten tracks. |

> This Space should be **Private** — the repository contains your personal
> library export files.
