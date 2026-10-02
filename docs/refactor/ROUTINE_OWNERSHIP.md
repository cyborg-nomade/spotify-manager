# Item 6 ownership audit

Every original command is accounted for below. The public CLI and HTTP entry
points remain compatibility adapters; their decomposition and shared job
mechanics are roadmap item 7. Structural migration retains synchronous execution.
Native async transport, asynchronous orchestration and proven read concurrency
remain items 8–10.

Listening decisions belong to `domain`; invocation order, interaction and
accepted-effect/checkpoint boundaries belong to `application`. Environment,
client and concrete persistence construction belongs to `bootstrap`. Codecs,
raw response parsing and remote/file operations belong to `infrastructure`.
Existing source paths retain small SDK compatibility seams so public callbacks,
request parameters, retry scopes and the frozen endpoint inventory remain intact.

Operator commands that display, edit, hydrate or publish shared state/artifacts
continue to use their existing typed services. They have no independent listening
policy to migrate. OAuth refresh and cache rotation remain in the original client
adapter for transport item 8; Item 6 does not alter token-cache semantics.

## Original command coverage

| Original command | Workflow/policy destination or retained operator boundary |
| --- | --- |
| `album-decision` | `application.album_review`; `bootstrap.albums` |
| `analyse-comp` | `application.legacy_library_conversion.analyse` |
| `analyse-library-async` | `application.library_analysis_run`; export, checkpoint and publication stages |
| `analyse-library-sync` | `application.library_analysis_run`; live artist/offset and publication stages |
| `artist-stats` | `application.library_lookup_run.artist_statistics`; `domain.lookup_selection` |
| `blast-from-the-past` | `application.historical_selection`, `historical_resolution`, `historical_playlists` |
| `blast-from-the-past-artists` | `application.dormant_tracks`, `dormant_recovery`; `domain.dormant_artists` |
| `check-new-releases` | `application.release_opening`, `release_run`, `release_review`, `release_progress` |
| `compare-lib-files` | `application.legacy_library_conversion.compare`; `domain.legacy_library` |
| `convert-lib` | `application.legacy_library_conversion.convert` |
| `count-artists` | `application.legacy_library_monthly.count_artists` |
| `daily-mind-radio` | `application.historical_selection`, `historical_resolution`, `historical_playlists` |
| `fill-palace-of-memory` | `application.palace_run`, planning, history, mirror and cursor stages |
| `fill-queue-from-lastfm` | `application.queue_fill`, candidates and recommendations stages |
| `fill-sauvignon-from-lastfm` | `application.sauvignon_run`; album recommendation selection and resolution |
| `flush-new-kids` | `application.discovery_run`, planner, completion, review and reconciliation stages |
| `flush-new-wine` | `application.new_wine`, planner and execution; `application.wine_cellar` |
| `flush-queue` | `application.queue_flush`, planning and execution stages |
| `flush-queue-2` | `application.queue_2`; shared discovery planner, execution and reconciliation |
| `flush-queue-3` | `application.queue_3_run`, import, planner, execution and review stages |
| `flush-requeue-for-a-dream` | `application.requeue`; pure progression and explicit listening ports |
| `flush-slow-listening` | `application.slow_listening`, plan and state stages |
| `found-art` | `application.recommendation_run`; seed, candidate, resolution and result stages |
| `genre-reveal` | `application.genre_run`, progress and values; `domain.genres` |
| `import-queue-3-previous-year` | `application.queue_3_import`, import review and state stages |
| `library-data-pull` | Existing `core.library_data.service.LibraryDataService.hydrate` at the operator boundary |
| `library-data-push` | Existing `core.library_data.service.LibraryDataService.publish` at the operator boundary |
| `library-data-status` | Existing `core.library_data.service.LibraryDataService` artifact observations |
| `monthly-routines` | `application.legacy_library_monthly`; injected control, statistics and playlist stages |
| `new-year` | `application.new_year_run`, planning, charts, execution and history stages |
| `plan-discographies` | `application.discography_planning`, execution, catalog, history and queues stages |
| `recover-removed-albums` | `application.album_recovery`, artist follows and recovery values |
| `refresh-spotify-tokens` | Existing `client.RotatingSpotify.refresh_all_app_tokens`; original cache/rotation adapter |
| `restore-library-sync` | `infrastructure.library_analysis_files`; original backup/restore publication boundary |
| `restore-your-library` | `application.legacy_library_conversion.restore` |
| `review-album-limits` | `application.album_limits`, artist follows and library statistics stages |
| `review-artists` | `application.artist_review_run`, decisions, catalog, recovery and state stages |
| `something-old` | `application.something_old_run`, golden selection and values stages |
| `state-edit` | Existing `core.state.service.StateService` validation, merge and compare-and-swap boundary |
| `state-export` | Existing `core.state.service.StateService` snapshot/export boundary |
| `state-show` | Existing `core.state.service.StateService` snapshot boundary |
| `update-scrobble-history` | `application.history_refresh`; pure merge and explicit file/API boundaries |
| `update-total-albums` | `application.legacy_library_refresh`; original raw paging and partial fallback authority |
| `upload-library-files-to-hf` | `application.upload_run`; `domain.upload_manifest`; file and Hub adapters |

## Related processors and operational entry points

- Live/local artist, album and track resolution: `application.lookup_resolution`,
  `library_lookup_run` and `scrobble_lookup_run`; exact matches, edition fallback,
  primary-credit ties and local seasons in `domain.lookup_*`.
- Legacy control, total-album, statistics, conversion, monthly and count helpers:
  `application.legacy_library_*`; permissive selection/batching/proportions in
  `domain.legacy_library`; JSON publication in `infrastructure.legacy_library_files`.
- Export fallbacks, local history buckets, Random.org records and playlist
  observations: dedicated infrastructure codecs with pure historical qualification
  and explicitly supplied clocks, retries, cancellation and SDK reads.
- Web password gate: pure `domain.web_access`, direct-peer parsing in
  `infrastructure.web_peer`, deployment wiring in `bootstrap.web`. The original
  header/read/bypass precedence and constant-time comparison remain.
- Settings and API/CLI startup: `bootstrap.settings` and `bootstrap.startup` retain
  the original fields, aliases, dotenv loading, warning and hydration callbacks.
- Nightly refresh: standard-library application coordinator, domain maintenance
  calendar and infrastructure HTTP/response codecs. The executable script keeps
  its arguments and callback seams and imports without installed app dependencies;
  Python 3.13 syntax remains supported for its Actions environment.

## Dependency audit and compatibility limits

Every domain module imports without SDKs, settings, Pydantic, models, files or
application startup. Every application module imports without SDK, infrastructure,
bootstrap or runtime construction. Isolated tests construct typed dependencies
independently of production composition and replay the original observations.
Routine modules no longer call another routine's private helper; the two shared
historical direct-call defaults now have an application owner. Remaining private
references from an adapter/composition module to its own compatibility facade are
explicit original SDK, codec, state or presentation seams rather than imported
listening rules. Interface job/state display helpers are accounted for in item 7.

The frozen files remain unchanged. OpenAPI, CLI, settings and storage contracts
are compared in full. Only source line numbers are removed from route/Spotify
inventory comparisons; paths, handlers, methods, models, SDK expressions, source
paths, request parameters and reference counts remain checked. Tests also require
the checker to reject changed route or endpoint identity.

Preserved legacy limitations include differences in preview writes, partial
accepted-effect recovery, duplicate/status handling, native malformed-record
errors, fallback source authority and temporary-file cleanup. These are documented
throughout `ROUTINE_FAMILIES.md` and are not repaired by this structural refactor.
