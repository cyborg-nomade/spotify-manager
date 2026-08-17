# Web Application and API

## Two ASGI applications

The project exposes the same FastAPI object through two entry points with
different trust boundaries.

| Entry point | Frontend | Password gate | Intended use |
| --- | --- | --- | --- |
| `spotify_manager.api:app` | No | No | Loopback development, tests, or a trusted external wrapper. |
| `spotify_manager.web:app` | Yes | Yes, when `APP_PASSWORD` is set | Local cockpit and Hugging Face deployment. |

`spotify_manager/web.py` imports the API app, adds middleware and frontend
routes, and serves the cockpit. It does not duplicate the command logic.

## Running locally

### Gated cockpit

```console
uv run --env-file .env uvicorn spotify_manager.web:app \
  --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000`. The `--env-file` option matters because the web
wrapper reads `APP_PASSWORD` directly from the process environment.

### Pure API

```console
uv run spotify-api
```

or:

```console
uv run --env-file .env uvicorn spotify_manager.api:app \
  --host 127.0.0.1 --port 8000 --reload
```

The generated OpenAPI interfaces are available at `/docs`, `/redoc`, and
`/openapi.json`. The pure API is ungated, so keep it on loopback.

## Authentication

`PasswordMiddleware` compares the `X-App-Password` header with
`APP_PASSWORD` using a constant-time comparison. The shell pages and liveness
route are open so the browser can load the login interface and the platform can
check health:

```text
/
/index.html
/genre-reveal
/genre-reveal/
/health
/favicon.ico
```

Every other route is protected when `APP_PASSWORD` is configured. A missing or
incorrect header returns HTTP 401 with `{"detail":"unauthorized"}`.

Example:

```console
curl -H 'X-App-Password: YOUR_PASSWORD' \
  http://127.0.0.1:8000/auth/check
```

If `APP_PASSWORD` is not set, middleware enforcement is disabled and a startup
warning is logged. Never deploy the Space in that mode.

## Cockpit structure

The frontend is one static HTML application with no compilation step. It is
responsive from a one-column mobile layout to a modular desktop control panel.
Routine cards are organized by listening function:

- data signals and source-history refresh;
- recovery tracks;
- discovery tracks and artist queues;
- deep listening;
- album cycles;
- release discovery and discography planning; and
- live library instruments.

Cards start cautious routines in dry-run mode, expose command-specific compact
controls, and show terminal logs on demand. Pending choices are rendered in the
card rather than using blocking browser dialogs. Controls remain available when
the viewport wraps on mobile.

The **Library instruments** call live Spotify lookups. Their single input accepts
a name, raw Spotify id, URI, or share link. The **Data signal board** starts
independent album, track, and artist mirror refreshes and shows server file
timestamps, including Last.fm history.

Legacy library cards and generic command buttons are intentionally absent from
the current UI, but their API routes remain available.

## Background-job protocol

Long-running commands return immediately with a job snapshot. The frontend
polls the job route instead of holding one request open.

### Common lifecycle

1. `POST /commands/COMMAND` starts a job.
2. `GET /commands/COMMAND-jobs` lists active jobs for page-reload recovery.
3. `GET /commands/COMMAND-jobs/{job_id}` returns current status, progress,
   results, pending choice, retry time, and logs.
4. Interactive commands accept
   `POST /commands/COMMAND-jobs/{job_id}/choice`.
5. Cancellable commands accept
   `POST /commands/COMMAND-jobs/{job_id}/cancel`.

Not every routine needs choices or cancellation, so consult `/docs` for its
exact routes and request model.

### Status values

| Status | Meaning |
| --- | --- |
| `queued` | Job object exists but work has not started. |
| `running` | Worker thread is executing. |
| `waiting` | Worker is waiting for a user choice or scheduled retry. |
| `cancelling` | Cancellation was requested and is awaiting a safe boundary. |
| `cancelled` | Worker stopped cleanly. |
| `paused` | Routine stopped at a durable resumable boundary. |
| `completed` | Work finished successfully. |
| `failed` | Work ended with an unrecovered error. |

Job logs carry a sequence number, UTC timestamp, and display message. The API
retains the latest 250 entries per in-memory job. The frontend uses sequence
numbers to avoid duplicating lines while polling.

An active-job collection allows the page to reconnect after a browser reload.
It does not survive a server-process restart. Routine state files provide
cross-process resumability where implemented; displayed in-memory logs are
replaced by the persistent JSON-lines audit trail.

Starting a second active instance of the same command returns HTTP 409. This
prevents two workers from mutating one playlist or state file concurrently.
Blast from the Past and Daily Mind Radio use bounded, cancellable Spotify
requests; their cancel controls stop retry waits immediately and stop an active
HTTP request at its configured timeout boundary.

## Endpoint families

The generated OpenAPI schema is authoritative. The table below is an operator
map rather than a replacement for the request/response models.

### Health and live lookups

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Public liveness response. |
| `GET /auth/check` | Verify the supplied app password. |
| `POST /library/refresh` | Clear and reload the cached parsed `YourLibrary.json` used by legacy endpoints. |
| `GET /library-mirrors/status` | Return existence and update time for canonical server files. |
| `GET /artists/stats` | Live liked-track and saved-release counts for an artist reference. |
| `GET /albums/evaluation` | Live liked-track evaluation for an album reference and threshold. |

### Library analysis

```text
POST /commands/analyse-library-async
POST /commands/analyse-library-sync
POST /commands/refresh-library-mirrors
POST /commands/refresh-library-mirrors/{albums|tracks|artists}
GET  /commands/library-analysis-jobs
GET  /commands/library-analysis-jobs/{job_id}
POST /commands/library-analysis-jobs/{job_id}/cancel
```

Analysis jobs expose per-resource counts and status, full/incremental mode,
retry time, run id, backup path, and event logs.

### Recovery and recommendation jobs

```text
/commands/blast-from-the-past[-jobs]
/commands/daily-mind-radio[-jobs]
/commands/found-art[-jobs]
/commands/fill-sauvignon-from-lastfm[-jobs]
/commands/fill-queue-from-lastfm[-jobs]
/commands/something-old[-jobs]
/commands/update-scrobble-history[-jobs]
```

The Sauvignon, Queue, and Something Old families include choice/cancel routes
where ambiguity or mode selection can pause the worker.

### Playlist progression jobs

```text
/commands/flush-queue[-jobs]
/commands/flush-new-kids[-jobs]
/commands/flush-queue-2[-jobs]
/commands/flush-queue-3[-jobs]
/commands/flush-new-wine[-jobs]
/commands/flush-slow-listening[-jobs]
/commands/flush-requeue-for-a-dream[-jobs]
/commands/fill-palace-of-memory[-jobs]
```

Most progression jobs support cancellation. Commands that cross release
boundaries or select catalog alternatives also expose `/choice`.

### Planning and discovery jobs

```text
/commands/check-new-releases[-jobs]
/commands/plan-discographies[-jobs]
```

Both families expose choice and cancel endpoints and persist durable progress
through their routine state files.

New Release Check also exposes a protected restart-recovery handshake:

```text
GET /commands/check-new-releases-state[?known_fingerprint=...]
PUT /commands/check-new-releases-state
```

The cockpit keeps the latest full snapshot in browser storage. Polls send the
known fingerprint, so an unchanged response omits the large state body. A PUT
requires the fingerprint of the server copy that was compared, accepts only a
newer semantic timestamp, refuses to run beside an active release check, and
creates a server-side backup before replacement.

### Genre Reveal routes

These routes are added by `spotify_manager.web:app`:

| Method and path | Purpose |
| --- | --- |
| `GET /genre-reveal` | Serve the preserved nearest-neighbor interface. |
| `GET /genre-reveal/state` | Read completed genres and view preferences. |
| `PUT /genre-reveal/state` | Atomically replace route state with backup. |
| `GET /genre-reveal/source` | Resolve a genre's source Spotify playlist. |
| `POST /genre-reveal/run-next` | Save and sample the first incomplete genre. |

The run endpoint uses a process lock and returns HTTP 409 when another Genre
Reveal operation is active.

### Legacy command endpoints

The API retains synchronous endpoints for monthly routines, total-album update,
export restoration, file comparison, comparison analysis, conversion, and
artist count. They are not displayed in the current cockpit.

## Calling the API directly

Start an analysis:

```console
curl -X POST \
  -H 'X-App-Password: YOUR_PASSWORD' \
  'http://127.0.0.1:8000/commands/refresh-library-mirrors/tracks?full_rebuild=false'
```

Poll the returned job id:

```console
curl -H 'X-App-Password: YOUR_PASSWORD' \
  http://127.0.0.1:8000/commands/library-analysis-jobs/JOB_ID
```

Cancel at a safe boundary:

```console
curl -X POST \
  -H 'X-App-Password: YOUR_PASSWORD' \
  http://127.0.0.1:8000/commands/library-analysis-jobs/JOB_ID/cancel
```

Use the OpenAPI schema to confirm query names and choice-body fields before
automating an interactive routine.

## Error semantics

| Status | Typical meaning |
| --- | --- |
| 400 / 422 | Invalid reference, option combination, query, or choice body. |
| 401 | Missing or incorrect `X-App-Password`. |
| 404 | Entity or job id not found. |
| 409 | Another job is active, a choice is stale, or live state changed since planning. |
| 429 | All configured Spotify credentials are rate-limited; inspect `retry_at` or the detail. |
| 500 | Local configuration, state, log, or unexpected application error. |
| 502 | Upstream Spotify, Last.fm, or Every Noise response could not be completed safely. |

The shared Spotify client retries short GET connection resets and rotates
credentials after 429. Interactive jobs also surface retry logs and retry times
instead of leaving the UI silently blocked. A persistent upstream failure ends
the job with a concise recoverable error while preserving routine state.

## Operational behavior

- Free or sleeping Spaces can need a warm-up request. The client retries the
  transient connection failures most commonly seen immediately after wake-up.
- Browser reload is safe during a running job; the card queries the active-job
  collection and resumes polling.
- Server restart is different from browser reload. The worker thread ends, and
  only routine files survive if they were preserved by storage or deployment.
  New Release Check is the exception: the same browser automatically restores
  its newer checkpoint mirror after reconnecting.
- Do not deploy while jobs are active or waiting for a choice.
- The cockpit is a single-user control surface. It does not provide per-user
  authorization, CSRF tokens, or multi-user job isolation.

## Web tests

Relevant coverage lives in:

```text
tests/test_web.py
tests/test_auth.py
tests/test_api.py
tests/test_api_job_failures.py
```

Routine-specific CLI and API tests verify the same choice and result adapters.
Run the full gate with `just test` before deployment.
