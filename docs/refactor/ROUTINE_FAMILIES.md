# Item 6: routine family migration

**Status:** in progress on `codex/refactor-06-routine-families`, based on item 5's
merge `3d7c1df`. This document records checkpoints, not completion of item 6.
The full milestone remains one PR under the approved roadmap.

## Wave inventory

| Wave | Status | Destinations |
| --- | --- | --- |
| Foundation | Implemented and verified | Album review/recovery and artist-follow use cases in `application`; date policy in `domain`; explicit wiring in `bootstrap`; presentation and legacy integration adapters. |
| Release progression | In progress | Composer matching/observations and Slow Listening implemented; New Wine, New Kids/Queue 2, Queue 3 and shared Requeue integration remain. |
| History and discovery | Pending | History, radio, discovery, releases, The Queue and genre workflows. |
| Deep listening and retrospectives | Pending | Something Old, Palace of Memory, Discography and New Year. |
| Library and legacy workflows | Pending | Analysis, artist review, conversion, monthly workflows, counts and remaining loaders/processors. |
| Operational integration | Pending | Uploads, authentication/settings, automation and startup. |

## Foundation responsibilities

`review_album_limits` and `recover_removed_albums` retain their public entry
points and delegate through composition into injected application workflows.
The application owns the order of observations, choices, accepted mutations,
mirror publication, statistics, audit and checkpoints. The presenters preserve
messages and prompt boundaries. The infrastructure adapters retain the original
parsers, file formats, retry settings and caller-owned Spotify client.

Artist following has two named services because the workflows differ. Album
review checks one artist and records only newly followed artists; recovery batches
credits, preserves duplicate ordering and refreshes all checked artist records.
Their statistics transformations also remain distinct: recovery clamps the
artist denominator while review retains its original zero-division behavior.

Validated library/statistics models are reused. Existing album lookup batching
and pure threshold policy remain behind the already established ports; no second
schema hierarchy or generalized workflow engine is introduced. Shared retry
policy and artifact metadata now have infrastructure owners, eliminating imports
from the review routine for these unrelated responsibilities. SDK expressions
remain in small compatibility helpers while the transport is still synchronous.

Recovery deliberately preserves accepted-effect failure behavior. Artist mirror
publication precedes artist audit/checkpoint; album mirror publication precedes
album audit/checkpoint. In-memory checked/processed sets can change before a
failed durable write. Dry runs still change those in-memory sets. Future-date
parsing retains tolerant partial-date behavior, and oversized album responses
still follow their credited artists before the original strict-zip failure.

## Foundation evidence

- 1,681 tests pass in the full suite, randomized with seed `20260932`.
- Coverage: 91.09% statements (17,369 / 19,069), 76.16% branches
  (3,954 / 5,192). The legacy branch measurement remains diagnostic.
- The 129 existing frozen traces are unchanged. Twenty additional recovery
  traces were captured from the pre-migration implementation at `3d7c1df`,
  covering normal/preview execution and failures before/after nine effect
  boundaries, followed by restart.
- Independent gates pass 156 domain tests and 109 application tests, with 100%
  statement and branch coverage for their policy/use-case/value targets.
- Fourteen Foundation interface tests cover actual CLI invocation, action
  aliases, repeated invalid input and exact presentation. These two routines have
  no HTTP workflow route; existing state/schema tests cover their API exposure.
- All eleven public artifact comparisons pass, including the Spotify endpoint
  inventory with only source line numbers removed. Frozen snapshots stay intact.
- Package Ruff lint/format and mypy pass; the inner layers and their independent
  tests pass strict mypy and dependency-direction checks.

Reproduce with `just test-domain`, `just test-application`, the randomized full
pytest suite and the interface capture/comparison commands documented in
`VERTICAL_SLICES.md`. Subsequent wave evidence will be recorded below as each
wave is implemented.

## Release progression: composer discovery and Slow Listening

Composer matching now belongs to `domain.composers`. The adapter owns tolerant
Spotify page parsing and owner-anchor discovery. Fourteen additional observation
tests were first run against the original implementation, before moving that
boundary. The original routine re-exports its public values and functions.

Slow Listening now has an application workflow with explicit playlist, catalog,
state, audit and interaction dependencies. Its planner requests equal-date
ordering only when a transition reaches that date; its observations are cached
only within one invocation. Track mapping and date grouping are pure policies.
The application owns the existing durable records and preserves their tolerant
constructor behavior, including unknown fields/actions where previously allowed.

The run separately handles planning, accepted playlist changes, completion
acknowledgement, audit and checkpoints. It retains replacement-before-removal,
saved skips, pause/resume, live refresh after completion acknowledgement and the
legacy audit writes during previews. The unchanged synchronous SDK calls remain
behind compatibility integration helpers. Shared catalog loader ownership and
Queue 3's remaining private-helper dependencies will be addressed later in this
same release-progression wave.

Checkpoint evidence:

- The full randomized suite passes **1,794 tests** with seed `20260933`, including
  all unchanged frozen traces. Statement coverage is **91.44%** (17,734 / 19,394)
  and diagnostic branch coverage is **77.19%** (4,034 / 5,226).
- Independent domain and application suites each pass **182 tests**. Extracted
  policy/use-case/value targets retain **100% statement and branch coverage**.
- Five further CLI/HTTP integration tests pass with real command/job execution:
  tie ordering, track choices, preview, completion acknowledgement after removal,
  and restart after an accepted append whose removal fails. Worker cleanup is
  guaranteed by the test fixture. These tests do not replace the workflow with a
  stub.
- All eleven public artifact comparisons still pass; package mypy and Ruff pass.

This is a checkpoint within the release wave. Item 6 is not yet ready for review,
deployment or merge.

### Wine Cellar refill checkpoint

Wine Cellar refill now has an injected application use case. It owns pending
transfer intent, destination capacity, duplicate handling, library-affinity
checks, accepted additions/removals and audit order. Its presenter retains the
original transfer messages. The library-affinity service preserves album-first
membership checks, whole-batch counts, early stopping and omitted liked counts
when saved albums already qualify an artist. The main New Wine flush remains
under migration.

Eighteen refill traces were captured before changing New Wine at checkpoint
`19f6207`. They cover real/preview execution and failures before/after Spotify
append/removal, both audit records and four checkpoints. All remain unchanged
after extraction. The combined New Wine and characterization suite passes 178
tests; 35 independent refill/affinity tests cover every statement and branch in
the extracted services. The complete application gate now passes 220 tests with
100% coverage for its use-case/value targets. The eleven public artifact
comparisons also remain unchanged.

### New Wine flush checkpoint

New Wine now delegates through composition into an injected application workflow.
The planner owns source observations, streak progression, canonical endpoints,
current-year release choices and optional continuations. The executor owns album
qualification, ordered remote and mirror effects, marker membership projections
and durable progress. Presentation uses an explicit port; run-scoped caches keep
the original read boundaries. Durable records retain their original layouts,
coercions and tolerant handling of older plans.

The migration intentionally preserves differing failure contracts. Completed
entries are checkpointed before the result audit; skipped entries are audited
before their checkpoint. An accepted album removal can leave downstream mirror
or audit work incomplete on restart because the original workflow then observes
an absent album. Saved-plan execution still suppresses replacement writes after
source removal without requiring the replacement to remain present. None of
these behaviors has been silently repaired during extraction.

The legacy integration helpers now use typed module-level parsers, named sorting
keys and explicit loops. The public entry point, callbacks, messages and Spotify
expressions remain compatible. Shared catalog record types and live release
evaluation have application owners; broader shared-loader ownership remains part
of the New Kids/Queue 3 work in this wave.

Checkpoint evidence:

- All **1,973 tests** pass in the full randomized run (seed `20260934`).
- Coverage is **91.93% statements** (18,351 / 19,962), above the frozen 90.22%
  baseline, and **78.33% branches** (4,106 / 5,242). These are separate metrics.
  The diagnostic run used `--cov-branch` with the existing 90% combined pytest-cov
  floor and therefore returned a coverage failure at 89.10% combined coverage;
  the tests themselves all passed. Legacy branch coverage remains diagnostic.
- `just test-domain` passes **188 tests** and `just test-application` passes
  **327 tests**, both with **100% statement and branch coverage** for their
  configured targets. The application gate now includes the complete New Wine
  planner, executor, observations, state translation, plans and shared evaluation.
- The independent New Wine tests cover operator choices, exact read/effect order,
  canonical endpoints, accepted-effect failures, partial album removal and restart.
- Five additional real CLI/HTTP integration cases cover release choice, preview,
  canonical endpoint choice and restart after an accepted append.
- All eleven frozen public artifact comparisons pass, including the unchanged
  Spotify endpoint inventory. All existing characterization traces remain intact.
- Package and touched-test Ruff/format checks and mypy pass; inner-layer suites
  pass strict mypy and dependency-direction checks.

New Kids/Queue 2 and Queue 3 are next. This checkpoint does not complete Item 6.

### New Kids/Queue 2 assessment and history checkpoint

Artist-completion assessment is now an injected application service. Saved
membership is observed before catalog tracks; primary credits are filtered before
track-ID deduplication, with the first encountered track facts retained. Artist
top tracks are still observed even for an empty catalog. The popularity fallback
runs only when those top tracks supply no liked marker, preserving descending
title ties and the original shared track-cache behavior.

Ranked release and primary-credit track values now have domain owners. Promotion
reason translation and representative/fallback marker selection are pure
policies. Four observation tests were added and passed against the original
assessment before its extraction; all still pass afterward.

Current-year release completion now has a separate application observation
service. The inexpensive history prefilter intentionally unions matching release
titles across artists. The final completion rule then matches each track's actual
primary credit and requires every liked title. Catalog preference, edition-aware
title normalization, year filtering and distinct-title indexing have pure domain
owners. The shared title normalizer retains the Blast from the Past compatibility
entry point and unchanged behavior; the rest of that routine remains for its wave.

Checkpoint evidence:

- Full randomized suite: **2,014 tests pass**, seed `20260935`.
- Separate coverage: **92.05% statements** (18,513 / 20,111) and **78.67% branches**
  (4,141 / 5,264). The statement baseline passes; legacy branch coverage remains
  diagnostic. Capture both metrics with `--cov-branch --cov-fail-under=0`, then
  check the statement baseline separately rather than applying it to a combined
  metric.
- Independent gates: **210 domain tests** and **342 application tests**, with
  **100% statement and branch coverage** for their configured targets.
- The fresh-interpreter dependency test now imports every domain module, avoiding
  an outdated fixed list as new policies are added.
- All eleven frozen interface artifacts, package Ruff and mypy, and strict
  inner-layer checks pass. Existing characterization fixtures remain unchanged.

Composer routing, the New Kids/Queue 2 coordinator and Queue 3 remain in progress;
this checkpoint does not complete the release wave or Item 6.
