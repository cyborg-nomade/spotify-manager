# Item 8: native async Spotify transport

**Status:** approved, deployed and merged in PR #68.
The base is clean Item 7a merge `cb6f191`. Routine execution and the web/CLI
entry points keep their synchronous behavior until Item 9.

## Preceding release

The owner approved Item 7a PR #67 on 2026-10-26. Approved source
`fca21e549940ea7ba44b93777d3681a84a5b23a3` was deployed to Space revision
`b1a3c0cec8cf497f6a907147d0cd7824185f5d3a`. All 442 changed Python paths matched
those Git blobs; the state and canonical-data dataset revisions were unchanged.
The Space reached `RUNNING`. Authenticated checks passed before and after the
upload, including all four durable artifacts and all 20 reconnect endpoints:
[pre-deployment check](https://github.com/cyborg-nomade/spotify-manager/actions/runs/40304534643),
[post-deployment check](https://github.com/cyborg-nomade/spotify-manager/actions/runs/40304791583).
PR #67 was then merged. The four local runtime files were retained in a named
stash; older stashes were preserved. No temporary worktree remained.

## Direct transport path

```text
AsyncSpotifyRuntime.__aenter__
  → bounded OAuthProvisioner.open_sources
  → Credentials + one httpx.AsyncClient
  → AsyncSpotify.album / album_tracks / other named endpoint
  → SpotifyTransport.request(SpotifyRequest)
  → NativeSpotifyTransport.request
  → concrete HTTPX request + fixed response decoding
  ← original JSON value or compatible exception
AsyncSpotifyRuntime.__aexit__ → HTTP close + every OAuth source close
```

`application/ports/spotify_async.py` contains the SDK-free request values and
async transport/wait contracts. `infrastructure/spotify_async/client.py` spells
out the 24 SDK methods in the frozen application inventory, plus explicit raw
GET/POST/PUT/DELETE operations used by the integration leaves. There is no
runtime method generation or executable-operation dependency.

The endpoint adapter retains ID/URI normalization, batch order and duplicates,
query order, null omission, boolean encoding, embedded market queries, cursor
and offset URLs, trailing slashes, Unicode JSON serialization, empty payloads,
and the original playlist/library payloads. Pagination follows the supplied
next URL only when the caller explicitly requests it; it adds no prefetching.
Successful malformed JSON retains the SDK's `None` result. HTTP errors retain
status, message, reason and case-insensitive response headers.

## Credentials, retries and resource ownership

Each runtime owns its pool and credential state on one event loop. Reusing it
on another loop or after close fails explicitly. Pool capacity defaults to ten
connections; this is a resource bound, not an assumed Spotify rate quota.
No global async client is introduced.

A credential's lock covers its SDK token/cache observation and refresh. HTTP
requests and retry delays do not hold that lock. A separate rotation lock
coordinates the existing ordered primary/app5–app8 transition. Concurrent 429s
from the same older credential reuse the already activated alternate rather
than forcing another refresh. A request retains its selected credential across
connection retries even if another request changes the pool's active app.
Its own 429 transition is the only way it selects an alternate. This does not
expand the rotation policy.

The existing `SpotifyOAuth` implementation retains scopes, cache paths and JSON,
redirect behavior, local authentication and rotation's headless/missing-refresh
errors. Initial token acquisition keeps the SDK's original cache/authentication
behavior. A raw HTTP 401 is propagated, as in the synchronous client; it does not
silently trigger an additional replay. Expired cached tokens refresh through the
SDK and are coordinated before requests proceed. Force refresh and token reads
are separate named methods: activation happens before the next token read,
without an extra lookup. OAuth connection failures remain inside the original
outer GET retry boundary, including its unchanged method restriction.

Only OAuth/cache construction, token reads/refreshes and session cleanup use bounded
`asyncio.to_thread`. That standard-library API requires the four bound methods
recorded exactly in `tests/support/callback_policy.py`. No Spotify Web API request
runs in a thread. Cancellation retains capacity until a blocking operation
finishes, closes credentials returned after cancelled construction, and completes
resource cleanup before propagating cancellation.

The native adapter reuses urllib3's existing **retry policy object**, not its
blocking HTTP transport. Thus status budgets, total budgets, allowed methods,
backoff and the disabled-status sentinel remain intact. Adapter Retry-After
handling remains disabled; the existing outer routine policies retain ownership
of their own waits when migrated in Item 9.

| Boundary | Retained behavior |
| --- | --- |
| Default adapter profile | Five total/status retries; GET/POST/PUT/DELETE; 500/502/503/504; backoff factor 0.3. |
| Review/job profile | Zero adapter retries and status sentinel 999; failures return to the existing routine retry owner. |
| Adapter status exhaustion | The SDK's existing `SpotifyException(429, ..., "Max Retries")` mapping, including its original rotation consequence. |
| Connection establishment | Adapter connect budget runs before the existing outer GET connection budget. |
| Outer interrupted GET | At most `min(retries, 3)` retries, with delays 10, 20, 40 seconds. |
| Interrupted POST/PUT/DELETE after connection | Preserve ambiguous outcomes; no added outer replay. |
| HTTP 429 | Original ordered credential rotation and final response's Retry-After; no invented sleep or quota. |
| Notifications | The existing best-effort SDK display boundary moves to `client/events.py` and is shared by both transports. Its broad catch is relocated, not expanded to business execution. |

Shutdown closes HTTP and all credential sessions even if one cleanup fails.
Repeated close calls share completion. Cancelled callers wait for outstanding
OAuth/cache work to reach its completion boundary. The caller must still await
its application work before closing the runtime; job/task ownership and accepted
write/checkpoint cancellation are Item 9 work.

## Regression evidence

`tests/spotify_async/fixtures/requests.json` records 45 requests made by the locked
synchronous SDK using synthetic data only. Differential tests compare native
prepared requests to that SDK and independently keep those recordings frozen.
The original baseline and workflow recordings are not rewritten.

Deterministic tests cover success/null/malformed responses, exact error fields,
401, 429 exhaustion, every selected 5xx/method/retry combination, transport error
names, ambiguous writes, cache formats, refresh coordination, overlapping reads,
loop ownership, cancellation during HTTP/backoff/SDK work/construction/cleanup,
and partial initialization failures. Barriers establish concurrency; wall-clock
speed thresholds are not correctness gates.

`just test-spotify-async` runs lint, formatting, strict typing and a 100% statement
and branch coverage gate for the native transport, composition and shared event
boundary. The full package, isolated inner-layer and frozen-interface checks
remain required.

Final verification on 2026-10-26:

- **10,763 tests passed**, randomized seed `20261026`.
- Package statement coverage: **96.26%** (33,510 / 34,813); branch coverage:
  **92.80%** (5,668 / 6,108). Combined coverage is **95.74%**.
- Native transport, composition and shared event delivery have **100% statement
  and branch coverage**. The focused native and architecture checks pass
  **339 tests**; the reproducible native recipe passes **333 tests**.
- Separate isolated gates pass **1,201 domain** and **3,646 application** tests,
  both with **100% statement and branch coverage**.
- Ruff/formatting pass across **1,049 files**. Package plus standalone-script mypy
  pass **650 files**; strict inner-layer, native-adapter and test/support typing
  pass **471 files**. Changed functions pass the flatness, annotation, docstring,
  parameter-count and function-size audits.
- All **11 frozen public artifacts** match. Existing baseline/expected fixtures
  and frontend source are unchanged; the native HTTP recordings are additional
  synthetic-data evidence. All locked dependency versions are unchanged.
- Local review smoke checks pass for health, shared state, durable source status
  and all **20 reconnect endpoints**, with no active jobs or Spotify mutations.
  Four unrelated operator data files are preserved and excluded from the PR.


## Release and remaining work

The Item 8 review environment exercised the retained synchronous application
contracts. Its native adapter was tested independently. The active review
environment now follows [Item 9](ASYNC_EXECUTION.md).

Approved source `32a1a5e8af16d8b061446c37a6fc6d59df3e798c` was deployed to
Space revision `33047b35a2ef8f83c3c8b8dcd893b45bb81f9f89`; all 15 changed blobs
matched and the Space reached `RUNNING`. State and canonical-data dataset
revisions remained unchanged. Authenticated check-only workflows passed before
and after deployment, without running routines:
[before](https://github.com/cyborg-nomade/spotify-manager/actions/runs/40476053756),
[after](https://github.com/cyborg-nomade/spotify-manager/actions/runs/40476217024).
PR #68 then merged as `6ea10e4`. The rollback Space revision is
`b1a3c0cec8cf497f6a907147d0cd7824185f5d3a`. Four local operator files were
preserved in a named stash before returning to clean master.

Item 9 converts application execution, interactions and interface ownership to
async and installs this runtime at the web lifespan/CLI entry boundary. Item 10
then measures and optimizes independent reads. This item makes no live speedup
claim and does not change frontend structure, business policies, writes,
checkpoints or public schemas.

References: [approved lifetime decision](../adr/001-refactor-boundaries-and-async-lifetimes.md),
[HTTPX async ownership](https://www.python-httpx.org/async/),
[HTTPX pool limits](https://www.python-httpx.org/advanced/resource-limits/),
[Spotify rate limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits).
