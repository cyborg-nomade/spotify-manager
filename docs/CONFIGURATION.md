# Configuration and Local Execution

## Requirements

### Software

| Requirement | Purpose |
| --- | --- |
| Python 3.14 | Runtime version declared by `.python-version` and `pyproject.toml`. |
| `uv` | Creates the virtual environment, installs the locked dependencies, and runs entry points. |
| `just` | Optional but recommended command facade. Every Typer command has a same-named recipe. |
| Git | Source control and normal GitHub workflow. |
| Hugging Face CLI | Required only for Space operations and export uploads. Installed with `huggingface_hub`. |

`uv` may manage Python 3.14 for local development. The Docker image uses
`python:3.14-slim` and disables Python downloads during its locked install.

### Accounts and network services

| Service | Needed for |
| --- | --- |
| Spotify account and developer application | All live library, lookup, follow, save, and playlist operations. |
| Last.fm API key and username | Scrobble refresh, recommendations, Something Old, The Queue, and release checks. |
| Random.org access | Blast from the Past, Daily Mind Radio, and Palace of Memory. |
| Every Noise access | Genre Reveal. |
| Private Hugging Face Space and write token | Deployed cockpit and export uploads. |

There is no database, Redis instance, Node.js toolchain, or frontend build step.

## Installation

From the repository root:

```console
cp .env.example .env
just install
```

Without `just`:

```console
cp .env.example .env
uv sync
```

`uv sync` creates `.venv` from `uv.lock`, including the development dependency
group by default. The application and its two scripts are then available
through `uv run`.

Verify the installation without contacting an external service:

```console
uv run spotify-manager --help
just --list
```

## Spotify application setup

1. Create a Spotify developer application.
2. Register an explicit loopback redirect URI, for example
   `http://127.0.0.1:8080/callback`.
3. Put that exact URI in `SPOTIPY_REDIRECT_URI`.
4. Do not use `localhost`; the client rejects it before OAuth begins.
5. Fill `SPOTIPY_CLIENT_ID` and `SPOTIPY_CLIENT_SECRET` in `.env`.
6. Generate the local OAuth cache:

```console
just refresh-spotify-tokens
```

The browser consent requests these scopes:

```text
playlist-modify-public
playlist-modify-private
playlist-read-private
user-library-read
user-library-modify
user-follow-read
user-follow-modify
```

The primary cache is written to
`spotify_manager/auth/spotipy_token_cache.json`. It is ignored by Git and the
Docker build context.

### Optional credential rotation

Configure `APP5_CLIENT_ID` with `APP5_CLIENT_SECRET`, then the corresponding
pairs through `APP8_*`. Partial pairs are rejected. Run
`just refresh-spotify-tokens` again to authenticate each configured app.

The conventional cache files are:

```text
spotify_manager/auth/spotipy_token_cache.json
spotify_manager/auth/spotipy_token_cache_app5.json
spotify_manager/auth/spotipy_token_cache_app6.json
spotify_manager/auth/spotipy_token_cache_app7.json
spotify_manager/auth/spotipy_token_cache_app8.json
```

On Spotify HTTP 429, the client rotates from the primary app through app5,
app6, app7, and app8. It force-refreshes the selected app's token before
retrying. Multiple applications improve rate-limit recovery but do not remove
the need for cautious retry handling.

## Environment reference

Pydantic Settings reads `.env` from the repository working directory. Variable
names are shown in their conventional uppercase form; the existing lowercase
form is also accepted.

### Core settings

| Variable | Required | Description |
| --- | --- | --- |
| `SPOTIPY_CLIENT_ID` | Yes | Primary Spotify application client id. |
| `SPOTIPY_CLIENT_SECRET` | Yes | Primary Spotify application client secret. |
| `SPOTIPY_REDIRECT_URI` | Yes | Exact registered loopback callback URI. |
| `ALBUMS_TO_ADD` | Yes | Integer used by the legacy monthly album workflow. |
| `LIMIT` | Yes | Integer page/batch setting used by legacy workflows. |
| `APP_PASSWORD` | Web deployment | Shared password checked by the gated web app. The pure API does not use it. |
| `AUTOMATION_TOKEN` | Scheduled web jobs | Independent high-entropy token accepted through `X-Automation-Token`; it does not change the cockpit password. |

The first five fields are required to instantiate `Settings`, even when a
specific command does not use all of them.

### Additional Spotify applications

| Variable | Required | Description |
| --- | --- | --- |
| `APP5_CLIENT_ID` / `APP5_CLIENT_SECRET` | No | First alternate Spotify app. Configure both or neither. |
| `APP6_CLIENT_ID` / `APP6_CLIENT_SECRET` | No | Second alternate Spotify app. |
| `APP7_CLIENT_ID` / `APP7_CLIENT_SECRET` | No | Third alternate Spotify app. |
| `APP8_CLIENT_ID` / `APP8_CLIENT_SECRET` | No | Fourth alternate Spotify app. |

### Playlist settings

Playlist settings are optional at application startup and required only by the
commands that use them. Values may be raw Spotify playlist ids, Spotify URIs,
or share URLs unless a command's README section says otherwise.

| Variable | Consumer |
| --- | --- |
| `THE_QUEUE_PLAYLIST` | Fill and flush The Queue; artist review tier 1. |
| `THE_QUEUE_2_PLAYLIST` | Queue 2 and New Kids refill; artist review tier 2. |
| `THE_QUEUE_3_PLAYLIST` | Queue 3, discography cleanup; artist review tier 3. |
| `NEW_KIDS_ON_THE_BLOCK_PLAYLIST` | New Kids on the Block flush. |
| `GREAT_DISCOVERIES_2026_PLAYLIST` | Seed/current Great Discoveries destination used by New Kids. |
| `UNLUCKY_ONES_PLAYLIST` | Unsuccessful artist-review destination. |
| `BLAST_FROM_THE_PAST_PLAYLIST` | Blast from the Past. |
| `DAILY_MIND_RADIO_PLAYLIST` | Daily Mind Radio. |
| `GENRE_REVEAL_PLAYLIST` | Genre Reveal sample destination. |
| `FOUND_ART_PLAYLIST` | Found Art recommendations. |
| `NEW_WINE_FROM_OLD_BOTTLES_PLAYLIST` | New Wine flush. |
| `WINE_CELLAR_PLAYLIST` | New Wine refill and release discovery. |
| `NEW_VINTAGE_PLAYLIST` | Top-50 new-release destination. |
| `SAUVIGNON_TERRE_NEUVE_PLAYLIST` | Completed album/EP markers and album recommendations. |
| `SLOW_LISTENING_PLAYLIST` | Slow Listening. |
| `REQEUEUE_FOR_A_DREAM_PLAYLIST` | Requeue for a Dream. The misspelling is part of the current public setting. |
| `PALACE_OF_MEMORY_PLAYLIST` | Palace of Memory. |
| `SOMETHING_OLD_NEW_PLAYLIST` | Something Old, Something New. |
| `DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST` | Newfoundland discography queue. |
| `DISCOGRAPHY_MEMORY_LANE_PLAYLIST` | Memory Lane discography queue. |
| `DISCOGRAPHY_REQUEUE_PLAYLIST` | The Requeue discography queue. |

Keep the year in `GREAT_DISCOVERIES_2026_PLAYLIST` aligned with the setting
currently implemented in `Settings`. The routines can discover or create later
yearly playlists where documented, but changing the seed setting name requires
a code and configuration update.

### Last.fm settings

| Variable | Required | Description |
| --- | --- | --- |
| `LASTFM_API_KEY` | For Last.fm API routines | Read-only Last.fm API key. |
| `LASTFM_USERNAME` | For Last.fm API routines | Account whose scrobbles feed the canonical history. |

A Last.fm shared secret is not required because the project performs only
read-only API calls.

### Runtime and deployment-only variables

These are read directly by startup or runtime modules rather than by
`Settings`. They normally do not belong in the local `.env` template.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SPOTIPY_CACHE_PATH` | `spotify_manager/auth/spotipy_token_cache.json` | Override the primary local cache path. |
| `APP5_SPOTIPY_CACHE_PATH` ... `APP8_SPOTIPY_CACHE_PATH` | Adjacent `*_appN.json` files | Override alternate cache paths. |
| `SPOTIPY_CACHE_JSON` | None | Full primary cache JSON seeded by `start.sh` in the Space. |
| `APP5_SPOTIPY_CACHE_JSON` ... `APP8_SPOTIPY_CACHE_JSON` | None | Full alternate cache JSON secrets seeded by `start.sh`. |
| `GENRE_REVEAL_LOG_PATH` | Package files directory | Move the Genre Reveal audit log. |
| `SPOTIFY_MANAGER_STATE_BACKEND` | `hub` | Shared state adapter: `hub` in normal operation or `local` for isolated development. |
| `SPOTIFY_MANAGER_STATE_REPO` | `cyborg-nomade/spotify-manager-state` | Private HF dataset containing the single `state.json`. |
| `SPOTIFY_MANAGER_STATE_FILENAME` | `state.json` | Dataset path for the shared state document. |
| `SPOTIFY_MANAGER_STATE_TOKEN` | `HF_TOKEN` or cached local token | Token with read/write access to the private state dataset. Required in the Space. |
| `SPOTIFY_MANAGER_STATE_LOCAL_PATH` | `spotify_manager/files/state.json` | File used only when the backend is explicitly `local`. |
| `SPOTIFY_MANAGER_DATA_BACKEND` | `hub` | Canonical-file adapter: `hub` in normal operation or `local` for isolated work. |
| `SPOTIFY_MANAGER_DATA_REPO` | `cyborg-nomade/spotify-manager-data` | Private dataset containing the four compressed canonical artifacts and manifest. |
| `SPOTIFY_MANAGER_DATA_MANIFEST` | `manifest.json` | Dataset path for checksums, timestamps, and provenance. |
| `SPOTIFY_MANAGER_DATA_TOKEN` | State token, `HF_TOKEN`, or cached local token | Token with read/write access to the private library-data dataset. |
| `SPOTIFY_MANAGER_DATA_LOCAL_ROOT` | `spotify_manager/files/library_data_store` | Store directory used only when the data backend is explicitly `local`. |
| `PORT` | `7860` | Container listen port used by `start.sh`. |
| `PYTEST_REPORT_PATH` | `test_report.xml` | JUnit output path for `just ci-test`. |

GitHub Actions stores two repository secrets for the nightly trigger:

| Secret | Purpose |
| --- | --- |
| `HF_SPACE_TOKEN` | Authenticates the workflow to the private HF Space. |
| `AUTOMATION_TOKEN` | Passes the application gate without sharing or changing `APP_PASSWORD`. |

## Running the CLI

The installed entry point and the `just` recipes are equivalent:

```console
uv run spotify-manager COMMAND [ARGS]
just COMMAND [ARGS]
```

Examples:

```console
just artist-stats "Miles Davis"
just album-decision "Kind of Blue" --artist "Miles Davis" --threshold 0.5
just flush-new-wine --dry-run
```

Use command help as the authoritative option reference:

```console
just flush-new-wine --help
uv run spotify-manager check-new-releases --help
```

Run commands from the repository root so `.env` and conventional paths resolve
as expected. Start mutating routines with `--dry-run` whenever the command
supports it.

## Running the pure API

The package entry point starts the ungated API on `127.0.0.1:8000`:

```console
uv run spotify-api
```

For development with reload:

```console
uv run --env-file .env uvicorn spotify_manager.api:app \
  --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` for generated OpenAPI documentation. The pure
API has no shared-password middleware; do not bind it to a public interface.

## Running the web cockpit

Load `.env` into the process so `web.py` can read `APP_PASSWORD` directly:

```console
uv run --env-file .env uvicorn spotify_manager.web:app \
  --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000` and enter any non-empty text. Requests whose direct
socket peer is loopback accept that local sign-in; LAN clients and the deployed
Space still require the configured `APP_PASSWORD`. Protected API requests send
the entered value in the `X-App-Password` header.

If `APP_PASSWORD` is absent from the process environment, the gate is disabled
and a warning is logged. That is acceptable only on a trusted loopback
development server. The deployed Space must always define it.

## Updating source exports

Place fresh exports at these exact paths:

```text
spotify_manager/files/YourLibrary.json
spotify_manager/files/lastfmstats-man-et-arms.json
```

Validate before uploading:

```console
just upload-library-files-to-hf --dry-run
```

After `hf auth login`, upload either or both:

```console
just upload-library-files-to-hf
just upload-library-files-to-hf --your-library-only
just upload-library-files-to-hf --lastfm-only
```

The Last.fm upload also regenerates deterministic compressed base64 parts used
when the full JSON file is materialized as a large-file pointer in a deployment
environment.

## Troubleshooting configuration

| Symptom | Check |
| --- | --- |
| `localhost` redirect warning or insecure redirect | Use an explicit loopback IP and register the exact URI in the Spotify dashboard. |
| `code must be supplied` during OAuth | The redirect URI did not complete correctly; fix the loopback URI, then rerun token refresh. |
| Missing playlist configuration | Add the command-specific variable from the playlist table and restart the process. |
| `Wrong or missing password` | Confirm `APP_PASSWORD` is in the process environment, not only in an unloaded file. |
| Headless token-cache error | Regenerate the matching local cache and update its `*_SPOTIPY_CACHE_JSON` Space secret. |
| Optional app configuration error | Configure both id and secret for an app, or remove both. |
| Last.fm configuration error | Set both `LASTFM_API_KEY` and `LASTFM_USERNAME`; no shared secret is needed. |
