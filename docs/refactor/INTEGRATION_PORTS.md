# Item 4: integration ports and explicit composition

**Status:** approved, deployed, and merged in PR #63 on 2026-09-25.
The source baseline is item 3's merge,
`24bc53a`, on `master`. The [accepted ADR](../adr/001-refactor-boundaries-and-async-lifetimes.md)
and [approved roadmap](../REFACTOR_ROADMAP.md) define this milestone.

## Ownership

Application use cases receive explicit dependencies. The new read-only
`application.album_review.review_album` resolves an album, reads its ordered
tracks, requests current membership, and applies the existing domain policy.
It runs against typed in-memory dependencies without importing SDKs, settings,
runtime services, or wire models.

| Concern | Application contract | Production construction |
| --- | --- | --- |
| Album catalog | `AlbumCatalog` returns parsed `Album` and `Track` values. | `bootstrap.listening.album_review_ports` wraps the supplied synchronous client with `SpotifyAlbumCatalog`. |
| Liked Songs membership | `TrackMembership` accepts ordered IDs and returns current statuses. | `SpotifyTrackMembership` shares that client and the original twenty-ID batch helper. |
| Requeue playlist effects | `PlaylistAccess` reads markers and exposes individual append/remove operations. | `requeue_playlist` binds the existing parser, write helpers, and caller-selected retry callback. |
| Shared state | `StateStore` and `RoutineState` retain their original signatures. | `create_state_service(store)` reuses `StateService`; `configured_state_store(environment)` selects the existing adapter. |
| Durable library mirrors | `LibraryDataStore` retains read/restore/guarded-write operations. | `create_library_data_service(store, paths)` reuses the original integrity-aware service; `configured_library_store(environment)` selects its adapter. |
| Listening history | `ListeningHistory` returns typed scrobbles grouped by date. | `listening_history(path)` retains the existing loader, compressed fallbacks, timezone, and ordering. |
| Interaction, audit, time, randomness | Named callable types describe existing message, choice, retry, audit, clock, and random-timestamp dependencies. | Existing callbacks satisfy these contracts directly; `requeue_audit(path)` binds the original JSONL writer. |

These ports cover concrete needs of the initial slices. They do not replicate
the entire Spotify SDK. Add operations when migrating a use case that needs
them, keeping distinct retry and freshness rules visible.

## Composition and compatibility

`bootstrap.state` and `bootstrap.library_data` now own environment resolution,
concrete adapter selection, and the process caches. Their explicit construction
functions accept dependencies directly and do not read process configuration.
The cached getters retain the existing lazy, process-wide lifetime for current
CLI and web callers. No client is created or closed by the listening factories;
the supplied client's credentials, transport, and callback ownership are retained.

The old `core.state.runtime`, `core.library_data.runtime`, and storage-port modules
remain import facades. Both old and new getter imports refer to the same cached
functions. Protocol identities remain shared through the old imports.
The core state package no longer eagerly imports its legacy state resolver when
loading its services or models. The application layer cannot import runtime
factories, infrastructure, legacy routines, settings, or SDKs.

The existing state and library services are reused without rewriting their
algorithms. Namespace merge/conflict handling, compare-and-swap revisions,
retry limits, artifact validation, checksums, hydration, provenance, canonical
paths, and publication timing remain intact. Backend defaults, case handling,
token precedence, empty-string behavior, and fallback errors remain unchanged.
The heterogeneous legacy namespace JSON retains its existing `Any` boundary;
new music contracts use typed values.

The temporary `infrastructure.legacy` adapters call existing parsers and selected
private effect helpers. This dependency is confined to the compatibility bridge.
It avoids duplicating tolerant payload parsing or inventing a shared retry policy
before the routine migrations. At the item 4 boundary, the album use case was
proven against the old path but not substituted into public entry points.
Item 4 production changes were composition relocation, the shared membership
helper, and structural track annotations for Requeue writes. The subsequent
[item 5 slices](VERTICAL_SLICES.md) connect the complete album and Requeue flows
to these boundaries through the existing CLI/HTTP compatibility facades.

## Preserved details

- Album resolution still prioritizes direct IDs and retains exact-name matching,
  primary-artist disambiguation, 404 translation, and malformed-response errors.
- Catalog reads keep page order, duplicates, and missing IDs. Membership uses
  twenty-ID batches, makes no request for empty input, does not deduplicate, and
  retains the last observation for duplicate IDs. There is no added cache or retry.
- Legacy status lookup coerces even falsey raw IDs to strings, although those IDs
  are omitted from membership requests. `Track.membership_key` retains this
  boundary fact, including collisions between `0` and `"0"`, or `False` and
  `"False"`. Displayed missing IDs remain `None`.
- Requeue writes retain their exact endpoint payloads, append/remove ordering,
  retry descriptions, and exception propagation. The adapter does not replay a
  failed write or change the transport's existing retry behavior.
- Audit construction performs no write. Invoking the bound writer emits the
  same JSONL bytes and raises the same destination errors as the original helper.
- History reads preserve Berlin-local dates and all existing export fallbacks.

Async transport, concurrency, caching optimizations, job mechanics, and complete
workflow migration remain in their assigned later items.

## Verification

- **1,521 tests passed** with global randomized order, seed `20260928`, including
  all **129 unchanged frozen workflow traces**. This adds 81 tests over item 3.
- Full application coverage is **90.62% statements** (16,728 / 18,459) and
  **75.26% branches** (3,873 / 5,146). Full legacy branch coverage remains
  diagnostic; the existing statement floor is still satisfied.
- The new application, bootstrap, and legacy-adapter packages have **100%
  statement and branch coverage** in the full suite.
- `just test-application` runs **25 independent tests**, Ruff, and strict mypy.
  It excludes application fixtures and requires **100% statement and branch
  coverage of the album use case and its music values**. A fresh-interpreter test
  verifies SDK-free application imports; an import guard enforces inward dependencies.
- Differential adapter tests compare typed album results and complete SDK call
  traces to the original evaluator. Other tests cover batch boundaries, malformed
  pages/statuses, failures, search parameters, playlist payloads and retry calls,
  audit bytes, compressed history, token precedence, singleton reset, injected
  state conflicts, and library publication/hydration.
- Ruff lint/format and mypy pass for the package. Strict mypy also checks the new
  packages, tests, and updated runtime tests.
- The frozen comparison passes for ten byte-identical public artifacts and the
  Spotify endpoint inventory with only source line numbers removed. Neither
  baseline snapshots nor workflow fixtures were rewritten.

Reproduce the focused checks:

```console
just test-application
.venv/bin/pytest tests/application tests/bootstrap tests/infrastructure tests/core/state tests/core/library_data
.venv/bin/python docs/refactor/capture_baseline.py --write --output /tmp/spotify-contract-review
.venv/bin/python docs/refactor/check_interfaces.py /tmp/spotify-contract-review
```

The existing Starlette/TestClient deprecation warning remains. Dependency
upgrades are outside this structural milestone.

## Local review

After opening the PR, run its branch using the existing environment:

```console
.venv/bin/uvicorn spotify_manager.web:app --host 127.0.0.1 --port 8765
```

Review at <http://127.0.0.1:8765>. Check shared-state loading, library status, live
album evaluation, and a Requeue preview. The app uses the configured Spotify
credentials and shared state/data backends. Startup hydration refreshes local
canonical files; those runtime data changes are excluded from the PR.
Existing routine-specific preview effects still apply.

## Deployment record

The approved head `ffd2275ca276efe0562f318801d0e0d62458a45f` was deployed as
Hugging Face revision `ed3fdfd982e5ec210488302a5e2a801f99864ab0`. All 36 approved
files were verified; unrelated Space files and both state/data dataset revisions
were preserved. Authenticated production checks passed in GitHub Actions run
`36163084198`, including shared state, all four library artifacts, and 20 idle
job families. PR #63 was then merged and its branch removed. Item 5 started from
clean, updated `master` at `c4f808e`.
