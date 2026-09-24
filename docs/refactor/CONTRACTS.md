# Compatibility contracts at item 1

Baseline and reproduction instructions are in [README.md](README.md). The
individual registration checklist is [baseline/interfaces.md](baseline/interfaces.md).
This document records current behavior, including inconsistencies; it does not
authorize fixes. Source paths are relative to the repository root.

## Entry points and public interfaces

| Surface | Contract and evidence |
| --- | --- |
| Installed CLI | `spotify-manager = spotify_manager.main:app`; 44 commands, preserved option spellings/argument kinds/defaults. The same-named `justfile` recipes forward arguments. See [CLI capture](baseline/cli-commands.json). |
| Installed API | `spotify-api = spotify_manager.api:serve`; defaults to `127.0.0.1:8000`. Direct `spotify_manager.api:app` has no password middleware until `web` is imported. |
| Deployment | `start.sh` seeds separate OAuth cache files, then runs `spotify_manager.web:app` on `0.0.0.0:${PORT:-7860}`. Preserve Docker/startup paths. |
| Web import | `web.py` imports and modifies the same FastAPI `app`, adding middleware and seven routes. Its module docstring's implication of an unchanged app must not be treated as isolation. Capture pure OpenAPI before importing web, and clear the schema cache for web additions. |
| CLI startup | `initialize_shared_library_data` hydrates canonical files before commands except `library-data-status`, `library-data-pull`, and `library-data-push`. Subcommand help can run the callback. Startup hydration is separate from each command's dry-run behavior. |
| API startup | Async lifespan currently calls synchronous `hydrate_runtime_library_data`. Hydration failures are logged with fallback to local files unless strict mode is explicitly requested. |
| Source compatibility | Preserve installed/imported entry points, routine function entry points used by callers, settings spellings, and `just` recipes. Internal helper relocation is expected; it is not a public wire change. |

OpenAPI records declared validation and responses but does not enumerate every
runtime error. Keep exception translation in `api.py`, the web wrapper, and CLI
handlers, including 401/403/404/409/422/429/5xx paths. Existing evidence is in
`tests/test_api.py`, `tests/test_api_job_failures.py`, `tests/test_auth.py`,
`tests/test_web.py`, and `tests/test_cli_*`. Representative CLI output is frozen
in [cli-examples.json](baseline/cli-examples.json); these examples stub business
results and do not prove the computation behind them.

## Authentication and job protocol

`PasswordMiddleware` accepts `X-App-Password` and separately `X-Automation-Token`.
The automation token is accepted on all gated paths, not just automation routes.
With no configured password the gate is disabled. OPTIONS requests and the
`OPEN_PATHS` set bypass the gate. The exact set is `/`, `/index.html`,
`/genre-reveal`, `/genre-reveal/`, `/health`, and `/favicon.ico`; being allowlisted
does not itself register a route. An incorrect password returns JSON
`{"detail":"unauthorized"}` with HTTP 401.

Outside a Space (neither `SPACE_ID` nor `SPACE_HOST`), a nonempty password header
from a direct loopback peer is accepted. Forwarded headers do not establish
loopback identity. Preserve these distinctions when moving the middleware.

Jobs use `queued`, `running`, `waiting`, `cancelling`, `cancelled`, `paused`,
`completed`, and `failed`. Keep all currently emitted statuses and transitions,
not every theoretically possible transition. Logs retain at most 250 entries,
with sequence numbers and timestamps; result snapshots are detached copies.
Job handles/logs disappear on process restart. Durable routine progress is a
separate contract and does not mean the job registry is durable.

Conflicting start and invalid choice/cancel operations return the current 409
responses; unknown IDs or command/ID mismatches retain current lookup behavior.
The conflict rules are not uniformly one job per command: for example,
`cmd_new_year` rejects any active playlist/history job in `_blast_jobs`.
Starting other routines while an annual job is running must be characterized
from their own guards rather than assumed symmetric. Choice/cancel availability
is route-specific: Found Art, for example, has no cancel route in this baseline.

Keep `AnalysisJobResult` and `BlastJobResult` field names, absent/null/default
behavior, command strings, and pending-choice formats. A future typed internal
result may be presented through this same broad envelope. Frontend polling and
nightly automation are existing clients of these contracts.

## Selection, ordering, and effects

The [rule map](RULES.md) identifies the policies to preserve. Within every routine:

- Preserve first-seen/playlist order, ranking ties, Unicode/name normalization,
  release edition handling, primary-artist credits, and local/remote source choice.
- Preserve the exact chosen batch and advancement count. Newly refilled items
  must not accidentally be advanced again in the same run.
- Preserve actual mutation ordering, typically add replacement before removing
  the source. A new generalized executor cannot reorder saves, follows, playlist
  updates, audits, and durable checkpoints just because final state looks equal.
- Preserve live membership checks and each routine's existing resumption logic.
  Cache lifetime is part of decision freshness; do not reuse old likes/membership
  through a choice or write where current code refetches them.
- Preserve cancellation boundaries and partial-success behavior. A timeout after
  an accepted mutation does not prove the mutation failed.
- Preserve differing notions of time: UTC state/job timestamps, Europe/Berlin
  listening days/weeks in history routines, calendar-year scopes, Random.org's
  response timestamp, and local `datetime.now()` calls where currently used.

### Dry-run and write matrix

This table lists routine-body behavior. CLI startup hydration and cache loading
can add effects before the routine begins. It is not safe to infer read-only
execution from the command name or the presence of a dry-run flag.

| Commands/family | Current default / effects to preserve |
| --- | --- |
| `new-year` | Preview by default (`--dry-run/--apply`). Resolves the plan without applying Spotify or annual-state mutations; refresh and planning helpers retain their own dry-run behavior. |
| `update-scrobble-history` | Live by default. Dry run merges/reports without replacing history, backups, or update logs; inherited hydration remains distinct. |
| `check-new-releases` | Live by default. Dry run may refresh/persist history, confirmed artist mappings, and permanent artist skips; no playlist/release-decision application. Current progress batching is part of persistence behavior. |
| `fill-palace-of-memory` | Live by default. Preflight refreshes the album mirror even for a dry-run selection. Dry-run selection leaves its cursor alone; `--set-alphabetical-cursor` is an explicit persistent operation. |
| `flush-new-kids`, `flush-queue-2` | Live by default. History is refreshed before playlist progression, including its existing persistence behavior. Dry run projects transfers and decisions without Spotify writes; preserve logs/caches and skip applying routine progress. |
| `flush-new-wine`, `flush-queue-3`, `import-queue-3-previous-year`, `flush-queue`, `flush-slow-listening`, `flush-requeue-for-a-dream` | Live by default. No Spotify mutations during dry run; projected advancement, log behavior, existing prompt differences, and checkpoint boundaries remain routine-specific. Do not impose a single generic dry-run implementation. |
| `found-art`, `fill-sauvignon-from-lastfm`, `fill-queue-from-lastfm`, `something-old`, `blast-from-the-past`, `blast-from-the-past-artists`, `daily-mind-radio` | Live by default. Preview paths may read external services and update recommendation/history caches or audit output; preserve each helper's existing write rules. A full per-effect fault matrix is item 2 work. |
| `plan-discographies` | Live by default. Preview versus apply distinguishes selection from queue-marker removal and next-queue persistence. |
| `recover-removed-albums` | Live by default. Preview describes restoration/follow operations without applying them; keep recovery log/state and mirror timing as currently implemented. |
| `upload-library-files-to-hf` | Live by default. Dry run validates and plans uploads; applying materializes deterministic split exports and updates the Space's explicit file set, not durable state datasets. |
| `genre-reveal` | No dry-run option. Interactive source preview/confirmation and optional browser opening precede mutation. Web run saves the source playlist, adds missing tracks, logs, then marks completion. |
| `review-album-limits`, `review-artists` | No dry-run option; interactive decisions and existing automatic zero-like handling. Retain safe ordering and resumability. |
| `analyse-library-async`, `analyse-library-sync`, `restore-library-sync` | No dry-run option. Export mode writes only suffixed async outputs; live analysis writes sync outputs; restore replaces outputs from the selected backup after confirmation unless `--yes`. |
| `state-show`, `state-export`, `state-edit` | Show reads; export writes its requested snapshot; edit validates and confirms before revision-guarded replacement. `--force` changes stale-export handling, not the final compare-and-swap guard. |
| `library-data-status`, `library-data-pull`, `library-data-push` | Status reads metadata/local status; pull hydrates; push publishes after confirmation unless `--yes`. Repeated `--artifact` values are deduplicated in order; no values selects all artifacts. |
| `artist-stats`, `album-decision`, `count-artists` | Live lookup JSON for the first two, local export count for the last; they still inherit CLI hydration. Preserve cache/no-cache flags on the separate review commands. |
| `monthly-routines`, `update-total-albums`, `restore-your-library`, `compare-lib-files`, `analyse-comp`, `convert-lib` | Supported legacy operations without a generic preview mode; preserve comparison files, monthly playlist creation, restoration, and console output. |
| `refresh-spotify-tokens` | Authenticates/refreshes every configured app cache in order and restores the original active app; no playlist changes. |

Backend endpoint defaults are frozen separately in OpenAPI. Frontend controls
may choose safer defaults; do not overwrite API/CLI defaults to make them uniform.

## Settings and environment contracts

[settings.json](baseline/settings.json) captures every `Settings` field. Pydantic
settings are case-insensitive and use `.env`; initialization arguments outrank
environment, which outranks dotenv values. There are no declared field aliases.
Direct `os.environ` reads below do not gain dotenv support just because `Settings`
loads `.env`. Preserve required fields even for commands that do not use Spotify:
`SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`, `ALBUMS_TO_ADD`,
and `LIMIT` are currently required by model construction.

| Name/group | Meaning, default, or precedence |
| --- | --- |
| `APP5_CLIENT_ID/SECRET` through `APP8_CLIENT_ID/SECRET` | Optional complete pairs; primary then app5–app8 rotation order. Partial pairs are configuration errors. |
| `SPOTIPY_CACHE_PATH` | Default `spotify_manager/auth/spotipy_token_cache.json`, relative to process cwd. |
| `APP5_SPOTIPY_CACHE_PATH` through `APP8_SPOTIPY_CACHE_PATH` | Explicit override or client-derived suffix of the primary filename. `start.sh` instead supplies explicit conventional paths for alternate apps unless overridden; preserve both construction paths. |
| `SPOTIPY_CACHE_JSON`, `APP5_SPOTIPY_CACHE_JSON` … `APP8_SPOTIPY_CACHE_JSON` | Startup-only token-cache secrets; seeded with mode 600. Never snapshot their contents. |
| `SPOTIFY_MANAGER_STATE_BACKEND` | `hub` default; `local` alternative, case-folded. Other values rejected. |
| `SPOTIFY_MANAGER_STATE_REPO/FILENAME/LOCAL_PATH` | Default dataset `cyborg-nomade/spotify-manager-state`, `state.json`, and package `files/state.json`. |
| `SPOTIFY_MANAGER_STATE_TOKEN`, `HF_TOKEN` | Dedicated state token takes precedence over general Hub token. |
| `SPOTIFY_MANAGER_DATA_BACKEND` | `hub` default; `local` alternative. |
| `SPOTIFY_MANAGER_DATA_REPO/MANIFEST/LOCAL_ROOT` | Default dataset `cyborg-nomade/spotify-manager-data`, `manifest.json`, package `files/library_data_store`. |
| `SPOTIFY_MANAGER_DATA_TOKEN` | Falls back to state token, then `HF_TOKEN`, in that order. |
| `RELEASE_CHECK_STATE_PATH`, `RELEASE_CHECK_STATE_BACKUP_DIR` | API recovery-path overrides; defaults are the release-check module constants. |
| `GENRE_REVEAL_STATE_PATH`, `GENRE_REVEAL_LOG_PATH` | Web wrapper overrides; defaults are the Genre Reveal module constants. |
| `APP_PASSWORD`, `AUTOMATION_TOKEN`, `SPACE_ID`, `SPACE_HOST` | Direct web authentication/loopback configuration described above. |
| Playlist settings | Exact names in settings snapshot, including `REQEUEUE_FOR_A_DREAM_PLAYLIST` (existing spelling) and `GREAT_DISCOVERIES_2026_PLAYLIST` (existing year). Generalization requires a compatible migration. |
| `LASTFM_API_KEY`, `LASTFM_USERNAME` | Optional globally, validated for history/recommendation commands. No Last.fm write secret. |
| Automation `SPACE_URL`, `HF_SPACE_TOKEN`, `AUTOMATION_TOKEN` | Space gateway token and application automation token are different credentials. Default Space URL is recorded in the automation source inventory. |
| Startup `PORT`; recipes `PYTEST_REPORT_PATH` | Defaults 7860 and `test_report.xml`; preserve deployment/task entry behavior. |

See `environment_reads` and `path_definitions` in
[source-inventory.json](baseline/source-inventory.json) for exact expressions,
source locations, and all routine default paths. Built-in startup and recipe
variables are documented here because the Python AST inventory does not parse
shell or YAML. The `.env.example` template contains names, not active values.

## Storage and serialization

| Artifact | Current format and compatibility boundary |
| --- | --- |
| Shared state | Version 1 JSON object: `schema_version`, `created_at`, `updated_at`, `namespaces`; each namespace has `updated_at` and object `value`. Unknown keys survive general document validation. JSON rejects non-finite numeric values. |
| Namespace defaults | [13 namespace defaults and validators](baseline/state-defaults.json), including `new_year: {"years": {}}`. Active-run shapes are owned by each routine validator and effect sequence; do not replace them with a newly designed schema during extraction. |
| Revisions | Local state uses SHA-256 of file bytes and `missing` when absent. Hub uses dataset commit SHA. Namespace save loads a baseline, preserves unrelated namespace changes, rejects same-namespace changes, and retries outer write conflicts up to five attempts. |
| State persistence | Local adjacent `.tmp` replacement with instance lock; Hub parent-commit-guarded `create_commit`. Pretty JSON plus trailing newline for storage; canonical comparisons use sorted compact JSON. No claim of cross-process locking for local files. |
| Legacy state access | Explicit `StateService` wins; otherwise a non-default explicit legacy path uses the supplied file loader/saver; default paths use central state. Keep this dispatch and per-validator legacy conversions; there is no blanket automatic migration of arbitrary legacy files. |
| Canonical data manifest | Version 1 object with timestamps and `artifacts`. Per artifact: exact filename, `blob_path`, SHA-256, uncompressed byte size, update timestamp, source label. Managed names: `albums`, `tracks`, `artists`, `scrobbles`. |
| Managed payloads | `albums_total_new.json`, `liked_tracks_total.json`, `artists_total.json`: lists of existing Pydantic export models. `lastfmstats-man-et-arms.json`: username and scrobbles with track/artist/album/albumId/date; date is milliseconds. Preserve optional/legacy fields accepted today. |
| Hub publication | Gzip level 9 with `mtime=0`; blob and manifest share a guarded commit. Hydrate at the manifest's immutable revision and verify integrity. Do not publish partial staged scans. |
| Derived/legacy data | `stats_history.json`, `albums_total.json`, comparison/control/stats files, suffixed async/sync mirrors, and original `YourLibrary.json` retain their current shapes and print/load behavior. They are not all canonical Hub artifacts. |
| Logs, caches, staging | JSONL appends, JSON caches, adjacent atomic files, gzip history backups, and analysis staging/manifests. Paths are in the source inventory; concrete ownership is in [DATA_AND_STATE.md](../DATA_AND_STATE.md). Audit logs are not a replayable event store. |

Storage tests: `tests/core/state/`, `tests/core/library_data/`,
`tests/loaders_savers/`, plus per-routine state/backup/resume tests. Those tests are
evidence for existing semantics, not proof of cross-store transactions or recovery
for every failed write. New guarantees would change behavior.

## Retry profiles and cancellation

| Profile | Current behavior |
| --- | --- |
| Default `RotatingSpotify` | Requests/OAuth timeout 10s. `retries=5`, default `status_retries=5`; urllib3 retries 500/502/503/504 for GET/POST/PUT/DELETE. `read=False`; `respect_retry_after_header=False` at this transport layer. Outer GET connection/timeout handling retries at most `min(retries, 3)` with 10/20/40s waits. Do not describe these layered retries as one simple total-attempt bound. |
| Credential rotation | HTTP 429 tries each configured untried app, force-refreshes its token, skips unusable auth, and rethrows when exhausted. The lock covers the whole internal call/wait. CLI may authenticate interactively; web clients disallow missing headless caches. |
| Analysis/review client factories | `retries=0`, `status_retries=0`, status list `(999,)` disable transport retry loops; rotation still occurs. Both CLI and HTTP have distinct factory/caching paths. |
| Shared routine retry helper | `review_album_limits.retry_spotify_server_errors`: 5xx and connection/timeouts retry up to supplied total attempts. Most callers supply 3 attempts and fixed 10s waits. 429 becomes `SpotifyRateLimitError`; other statuses are translated/rethrown. The callable has no read/write classification, unlike the client's GET-only outer transport retry. |
| Live library analysis | `analyse_library.spotify_call`: 5xx/connection errors use 10s exponential backoff capped at 1,800s; default attempts unbounded. 429 becomes a rate-limit error. Logs retry metadata. CLI can rotate/retry immediately or quit; web retry waits are interruptible with `waiting` status. |
| Web playlist wrappers | Usually the shared 3-attempt helper with `Event.wait` cancellation. New Wine and New Kids/Queue 2 additionally repeat exhausted 429 operations after `max(1, Retry-After or 60)` and update `retry_at` while status remains `running`. Other workers may pause/fail instead; preserve their specific catches. |
| Last.fm | urllib 30s timeout; 3 retries beyond the initial attempt, 2/4/8s waits. Retries HTTP 429/500/502/503/504, transport failures, and API codes 11/16/29; malformed JSON/response shape fails explicitly. Progress callback and injected sleeper are current extension points. |
| Random.org / Every Noise | urllib requests with module timeout constants; errors translated by those modules. No fallback to local randomness and no implicit adoption of Spotify retry policy. |
| State/data writes | Compare-and-swap conflicts have store/service-specific handling. Hub state 429 is a configuration error with durable previous-checkpoint guidance, not Spotify credential rotation. |

Exact call-site arguments are frozen under `retry_call_sites` in the source
inventory. Relevant existing tests include `tests/client/test_spotipy_client.py`,
`tests/client/test_lastfm_client.py`, `tests/routines/test_analyse_library.py`,
`tests/routines/test_review_album_limits.py`, and `tests/test_api_job_failures.py`.

## External endpoint inventory

These are the requests implied by **the installed, locked code**, not a claim
about which endpoints Spotify currently recommends. SDK names alone are not HTTP
contracts. [spotify-endpoints.json](baseline/spotify-endpoints.json) records
source arguments and SDK method bodies' delegated calls for verification.

| Integration | Used operations |
| --- | --- |
| Spotify catalog | GET `/v1/search`, `/v1/artists/{id}`, `/v1/artists/{id}/albums`, `/v1/artists/{id}/top-tracks`, `/v1/albums/{id}`, `/v1/albums/{id}/tracks/`, `/v1/albums/?ids=…`, `/v1/tracks/{id}`, `/v1/tracks/?ids=…`. Preserve country/market, include-groups, fields, limits, offsets, and null/missing-item handling. |
| Spotify user/library | GET `/v1/me`, `/v1/me/playlists`, `/v1/me/albums`, `/v1/me/tracks`, `/v1/me/following?type=artist`; GET `/v1/me/library/contains`; PUT/DELETE `/v1/me/library` with resource URIs. Locked Spotipy's older saved/follow methods delegate to the latter library endpoints. |
| Spotify playlists | GET/POST/PUT/DELETE `/v1/playlists/{id}/items`, with replacement/reorder/removal payloads preserved; POST `/v1/users/{user}/playlists`; Genre Reveal follows its source through PUT `/v1/me/library`. Several routines call private SDK HTTP helpers directly through `partial`. |
| Spotify pagination/auth | `next` follows returned links. SpotifyOAuth owns authorization and token refresh; current scopes are playlist read/write, library read/write, and follow read/write. Preserve cached-user auth, redirect validation, and per-app caches. No playback-control integration exists. |
| Last.fm | GET `https://ws.audioscrobbler.com/2.0/`, methods `track.getSimilar`, `artist.getSimilar`, `user.getRecentTracks`. Preserve autocorrection flags, range bounds, paging consistency checks, now-playing exclusion, and ms/sec conversion. |
| Random.org | GET `https://www.random.org/integer-sets/` for unique indices and HTTP response timestamp; used for historical dates and anniversary selection. This is not a call to the website's calendar-date UI. |
| Every Noise / embed | GET `https://everynoise.com/engenremap-{slug}.html` and `https://open.spotify.com/embed/playlist/{playlist_id}`; parse primary playlist and ordered public tracks. The route page itself is preserved local HTML. |
| Hugging Face | `repo_info`, revision-pinned `hf_hub_download`, and parent-guarded `create_commit` for state/data. Export uploader uses explicit Space file operations. Do not replace a dataset publication with a Space rebuild. |
| GitHub automation | `.github/scripts/nightly_refresh.py` calls the deployed `/health`, `/auth/check`, history-refresh and mirror-refresh job endpoints with gateway/app headers. Nightly jobs execute serially within the Berlin maintenance window; weekly full mirrors and monthly/Jan-1 full history are separate scheduling rules. |

## Explicitly deferred behavior questions

1. Shared cached Spotify callbacks can cross between overlapping jobs; a future
   ownership fix needs a reproducible test and explicit assessment of visible logs.
2. Mutation retries differ between transport and routine wrappers; blindly
   consolidating them could repeat an accepted write or remove existing retries.
3. Prose thresholds/order differ from implementation in places listed in RULES.
4. Generalizing misspelled/year-specific settings or the broad job response would
   break existing callers unless a compatibility migration is retained.
5. Current locks and process-local jobs do not promise distributed execution,
   cross-process file transactions, or durable job observability.

These are constraints for later milestones, not fixes implemented in item 1.
