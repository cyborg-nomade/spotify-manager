# Item 5: album evaluation and Requeue vertical slices

**Status:** implemented for review. Deployment and merge await owner approval
after PR review and local web testing. The source baseline is item 4's merge,
`c4f808e`, on `master`. The [approved roadmap](../REFACTOR_ROADMAP.md) and
[accepted ADR](../adr/001-refactor-boundaries-and-async-lifetimes.md) define this
milestone.

## Ownership and review order

Both workflows now execute application use cases through the existing public
entry points. They receive explicit integrations and apply pure domain rules.

| Layer | Album evaluation | Requeue for a Dream |
| --- | --- | --- |
| Existing entry points | CLI command and HTTP route call `evaluate_album_live`. | CLI command and HTTP job call `flush_requeue_for_a_dream`. |
| Composition | `bootstrap.albums` binds the caller's client to album ports. | `bootstrap.requeue` binds the client, retry callback, messages, audit path, and clock. |
| Application | `application.album_review` reads facts and invokes the album policy. | `application.requeue` gathers facts, plans, rechecks the head, performs ordered effects, and writes the audit. |
| Domain | Existing album keep threshold and typed music values. | Catalog values, edition selection, chronological successor, and a typed transition plan. |
| Integration | Existing album resolution, paging, and membership helpers behind legacy adapters. | Existing playlist/catalog parsers and individual append/remove operations behind legacy adapters. |
| Presentation | `interfaces.presenters.albums` converts the typed review to the existing wire model. | The original summary shape is now application-owned and re-exported for existing CLI/HTTP rendering. |

Start with `domain/requeue.py`, then `application/requeue.py` and its two ports.
The plan describes one transition; the use case owns the visible order of reads,
messages, writes, timestamps, and audit. Small top-level helpers keep each step
readable without introducing a workflow framework.

Immutable catalog dataclasses moved from New Wine and Slow Listening into
`domain.catalog`, retaining every field and default. Old imports re-export the
same class objects. `domain.discography` now owns edition preference, earliest
original chronology, stable tie-breaking, and canonical successor selection.
The shared loader still gathers the same facts at the same network boundaries.

Large CLI/HTTP handlers and job mechanics remain in their existing modules for
item 7. Their compatibility facades now dispatch into the migrated workflows;
tests invoke the actual commands, routes, and workers. Tolerant legacy payload
parsers remain behind `infrastructure.legacy` until the remaining routine families
are migrated. Async transport and concurrent reads remain assigned to later items.

## Preserved behavior

- Album lookup, malformed-response errors, pagination, membership batches,
  duplicate IDs, and falsey-ID/string collisions retain their previous semantics.
  The presenter retains field names, nulls, source, and cache indicators.
- Requeue selects the same source head, canonical studio edition, next release,
  and first playable track. Empty, skip, drop, and advance summaries are unchanged.
- A real drop or advance rechecks the playlist head immediately before effects.
  A replacement is appended before the source is removed. An already-present
  target is not duplicated. Request payloads and retry descriptions are unchanged.
- Dry runs retain their catalog reads but omit the final head recheck, mutations,
  and audit. Empty playlists have no audit; real skips still do.
- Progress callbacks retain their cancellation boundaries. The result timestamp
  is read after effects, and audit follows summary construction. Failures propagate
  at the same boundary, preserving any effect already accepted by Spotify.
- Requeue has no durable execution checkpoint. A restart reads the current list.
  If append succeeded and removal failed, the restart detects the replacement and
  avoids another append. If removal already succeeded, a restart evaluates the
  new head, including after an audit failure. No transactional guarantee is added.

## Verification

- **1,569 tests passed**, globally randomized with seed `20260930`, including
  all **129 unchanged frozen workflow traces**. This adds 48 tests over item 4.
- Full coverage is **90.72% statements** (16,860 / 18,585) and **75.43% branches**
  (3,883 / 5,148). Legacy branch coverage remains diagnostic; the statement floor
  is satisfied.
- `just test-domain` passes **137 independent tests** with **100% statement and
  branch coverage**. `just test-application` passes **50 independent tests** with
  **100% statement and branch coverage** for its use-case/value targets.
- The full suite covers every statement and branch in the domain, application,
  bootstrap, legacy-adapter, and new presenter modules.
- Ten synthetic album cases were captured from the pre-migration evaluator at
  `ffd2275ca276efe0562f318801d0e0d62458a45f`. The migrated public path is compared
  against those independent results and complete SDK call traces in
  `tests/infrastructure/fixtures/album_before_item5.json`.
- Requeue tests cover decision branches, exact effect order, changed/missing
  heads, dry runs, failures before and after accepted writes, audit failures,
  and restarts. CLI/HTTP tests exercise result translation, failure status, and
  an HTTP restart after append succeeds but removal fails.
- Ruff lint/format and package mypy pass. Strict mypy checks the extracted layers
  and their tests. Independent import tests enforce SDK-free inward dependencies.
- The interface comparison verifies ten byte-identical public artifacts and the
  Spotify endpoint inventory with only source line numbers removed. Existing
  baseline snapshots and workflow fixtures remain untouched.

The existing Starlette/TestClient deprecation warning remains unchanged.

Reproduce the focused checks:

```console
just test-domain
just test-application
.venv/bin/pytest tests/interfaces tests/infrastructure tests/characterization
.venv/bin/python docs/refactor/capture_baseline.py --write --output /tmp/spotify-contract-review
.venv/bin/python docs/refactor/check_interfaces.py /tmp/spotify-contract-review
```

## Local review

After opening the PR, run its branch with the existing environment:

```console
.venv/bin/uvicorn spotify_manager.web:app --host 127.0.0.1 --port 8765
```

Review at <http://127.0.0.1:8765>. Exercise live album evaluation and a Requeue
preview, then inspect the result and progress messages. The app uses configured
Spotify credentials and shared state/data backends. Startup hydration refreshes
local canonical files; these runtime data changes are excluded from the PR.

After approval, deploy the approved commit, verify the running revision and
authenticated production checks, merge, and return to clean `master` before item 6.
