# Item 6: routine family migration

**Status:** in progress on `codex/refactor-06-routine-families`, based on item 5's
merge `3d7c1df`. This document records checkpoints, not completion of item 6.
The full milestone remains one PR under the approved roadmap.

## Wave inventory

| Wave | Status | Destinations |
| --- | --- | --- |
| Foundation | Implemented and verified | Album review/recovery and artist-follow use cases in `application`; date policy in `domain`; explicit wiring in `bootstrap`; presentation and legacy integration adapters. |
| Release progression | In progress | Composer matching/observations, Slow Listening, New Wine and New Kids/Queue 2 implemented; Queue 3 and shared Requeue integration remain. |
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

### Composer progression checkpoint

New Kids composer routing now uses an application service over observed owned
playlists, an explicit choice callback and an injected clock. Valid saved routes
remain untouched; stale route removal still precedes skip, quit or selection
failure. Route acceptance retains the original timestamp and marker fields.

Composer works planning is independent of SDK/state I/O. It retains first-ID
mapping, unique normalized-title fallback, stored playlist order, the forty-work
limit and the original logical-composer credits. A missing liked top track still
takes precedence over otherwise qualifying promotion criteria. Completion still
uses the first work as the composer's destination marker.

The original routine re-exports its error classes and constants and keeps its
compatibility helper signatures. Release classification and source/composer
catalog adaptation now have pure domain owners. The main coordinator remains
under migration.

- Full suite: **2,048 tests pass**, randomized with seed `20260936`.
- Separate coverage: **92.10% statements** (18,585 / 20,179) and **78.83% branches**
  (4,159 / 5,276); the existing statement baseline remains satisfied.
- Independent gates: **221 domain tests**, **365 application tests**, both at
  **100% statement and branch coverage** for their configured targets.
- All eleven frozen public artifacts and unchanged characterization traces pass;
  package/inner-layer Ruff, format and mypy checks pass.

### Ordinary discovery planning and durable records checkpoint

New Kids and Queue 2 now share an injected ordinary-release planner. It observes
the current marker before reconstructing a missing streak, checks all primary
tracks after three unliked markers, and retains the original case-insensitive
title fallback without trimming whitespace. Completion evaluates guest tracks
too, writes the historical-progress audit before interaction, and checks every
remaining candidate before applying the preferred tier and ten-choice limit.

Durable source, release, track, progress, run and result translation now has an
application owner. Unknown fields, legacy-key removal, boolean streak values,
clock boundaries and malformed-record behavior remain characterized. The original
coordinator shares its existing observation caches with the new planner. Its
playlist effects, library reconciliation, refill and checkpoint orchestration
remain in progress; this checkpoint does not complete New Kids or Item 6.

- Full suite: **2,102 tests pass**, randomized with seed `20260937`.
- Separate coverage: **92.11% statements** (18,752 / 20,359) and **79.21% branches**
  (4,192 / 5,292); the frozen statement baseline remains satisfied.
- Independent gates: **223 domain tests** and **417 application tests**, both at
  **100% statement and branch coverage** for their configured targets.
- All eleven frozen interface artifacts, unchanged characterization fixtures,
  package Ruff/format/mypy and strict inner-layer checks pass.

### Discovery library reconciliation checkpoint

Release-boundary reconciliation now runs through an injected application service.
It retains live membership reads, remote changes, removal recovery records, mirror
publication, routine audit and presentation in their original order. Real runs
repair mirrors even when remote membership already matches; previews still read,
audit and display their decisions without changing the library or mirror.

Independent tests cover every saved/keep/preview combination and failures at each
effect boundary. A recovery-log failure after remote removal intentionally retains
the original retry behavior: the next attempt observes an absent album, repairs
the mirror and does not repeat the removal recovery record.

- Full suite: **2,120 tests pass**, seed `20260938`; **92.13% statements**
  (18,808 / 20,415) and **79.26% branches** (4,193 / 5,290).
- All **435 independent application tests** pass with **100% statement and branch
  coverage** for their configured targets; the 233 New Kids/characterization tests
  and all eleven frozen interface artifacts pass unchanged.
- Package lint, formatting and mypy pass. Playlist completion and coordinator
  extraction remain pending within the same Item 6 branch.

### Discovery execution checkpoint

Saved-plan execution and artist completion now have application owners. Release
reconciliation precedes playlist effects; Great Discoveries precedes Newfoundland;
replacement markers precede source removal; progress acknowledgment precedes the
coordinator's completion audit. Destination memberships remain scoped to one run,
deduplicating logical artists and projecting accepted additions during previews.

The original absent-source behavior is preserved: a missing replacement is still
secured before checking source presence. Missing liked top tracks still override
promotion qualification. Unfollowed artists retain the original skip of mirror
repair. Artist and composer progress retain separate timestamp reads, and unknown
actions and malformed optional records retain their original handling.

- Full suite: **2,157 tests pass**, seed `20260939`; **92.18% statements**
  (18,942 / 20,549) and **79.49% branches** (4,200 / 5,284).
- Independent gates: **223 domain tests**, **472 application tests**, both at
  **100% statement and branch coverage** for configured targets. The new executor
  and completion tests cover every branch, effect ordering and interrupted writes.
- All 233 New Kids/characterization tests and eleven frozen public artifacts pass;
  package/inner-layer lint, formatting and type checks pass.
- Great Discoveries creation, Queue 2 transfer/refill and shared run coordination
  remain to be extracted before this routine family is complete.

### Discovery destination creation and queue transfer checkpoint

Yearly playlist resolution now belongs to an application service. Stored IDs,
the configured 2026 seed, future-year previews, profile validation, private playlist
creation, namespace checkpoint and folder-placement messages retain their original
ordering. Checkpoint failures retain accepted IDs in the working namespace.

Queue 2 transfers now use a separate application service over explicit playlist,
audit and presentation boundaries. Capacity is checked before reconciliation,
logical composer credits control deduplication, additions precede removals, and
the destination list changes only after queue removal. Previews retain projected
membership, transfer audit and messages. Existing same-track/different-credit and
explicit-empty-queue behavior remain covered without tightening validation.

- Full suite: **2,188 tests pass**, seed `20260940`; **92.25% statements**
  (19,030 / 20,629) and **79.66% branches** (4,206 / 5,280).
- All **503 independent application tests** pass at **100% statement and branch
  coverage** for configured targets. Twenty-nine new tests cover destination and
  transfer decisions, remote failures, projection timing and checkpoint failures.
- All 233 New Kids/characterization tests, eleven frozen interface artifacts,
  package lint, formatting and type checks pass.
- Shared run coordination and Queue 2 invocation preparation remain in progress.

### Shared discovery entry coordination checkpoint

The entry coordinator now lives in the application layer and shares the accepted
planner/executor observations. Saved ordinary plans still observe the current
catalog before execution. New composer plans are checkpointed before the original
unconditional source reads; valid saved composer plans skip new route/works reads.
Stale plans clear their route, display the existing message, then checkpoint before
replanning or reporting malformed route state.

Ordinary skips still return a public result and audit before checkpointing.
Composer skips checkpoint before their message and produce neither that result
nor a skip audit. Pauses leave entries pending and stop before later entries.
Completion is acknowledged before its audit and final progress notification.

- Full suite: **2,212 tests pass**, seed `20260941`; **92.32% statements**
  (19,114 / 20,704) and **79.90% branches** (4,222 / 5,284).
- All **527 independent application tests** pass at **100% statement and branch
  coverage** for configured targets, including every entry-coordination branch.
- All 233 New Kids/characterization tests and eleven frozen interface artifacts
  pass; package and strict inner-layer lint, formatting and mypy checks pass.
- Run preparation/finalization and Queue 2 invocation preparation remain pending.

### Review lifecycle checkpoint

Run preparation and finalization now belong to an application service. Blocking
runs are checked before playlist reads; resumes retain saved entries and skip
prefill; fresh snapshots follow initial transfers and precede a separate live
membership read. Supplied Queue 2 selection and live sequences remain distinct.
Malformed saved entry sequences still fail between the original length and live
membership observations.

Completed runs checkpoint the refilling status before reloading live playlists,
then clear their active record after transfers. Paused runs omit both operations.
Previews retain the original fresh-live-read behavior during final refill rather
than using the simulated review projection.

- Full suite: **2,233 tests pass**, seed `20260942`; **92.35% statements**
  (19,152 / 20,739) and **79.96% branches** (4,225 / 5,284).
- Independent gates: **223 domain tests** and **548 application tests**, at
  **100% statement and branch coverage** for configured targets.
- All 233 New Kids/characterization tests and eleven frozen interface artifacts
  pass; package lint, formatting, mypy and strict application checks pass.
- Queue 2 invocation preparation and final composition cleanup remain in progress.

### Queue 2 invocation preparation checkpoint

Queue 2 preparation now has an application owner. Both playlist reads still precede
the New Kids blocking check. Matching active/refilling Queue 2 runs skip prefill;
other records use the original transfer rules. Previews ignore saved run blocking
and exclude their projected New Kids transfers from the remaining daily review.

Daily selection retains the first marker per logical artist up to the existing
limit while passing the complete remaining live queue into shared review. Summary
translation retains shared review's own pause/resume determination and final queue
length, alongside the original before/after New Kids counts.

- Full suite: **2,248 tests pass**, seed `20260943`; **92.34% statements**
  (19,172 / 20,762) and **79.98% branches** (4,226 / 5,284).
- All **563 independent application tests** pass with **100% statement and branch
  coverage** for configured targets, including all Queue 2 preparation branches.
- The 233 New Kids/characterization tests, all eleven frozen public artifacts,
  package lint/format/mypy and strict application checks pass.
- New Kids catalog parsing/ranking and final composition cleanup remain before
  declaring this part of the release-progression wave complete.

### New Kids/Queue 2 catalog and composition checkpoint

Canonical edition selection and catalog ordering now have a pure domain owner.
The saved/plain/popularity/top-track/date/title preferences remain distinct from
global review ordering, including first-observed edition ties and final identifier
ties. Release tracks retain stable disc/track ordering without deduplication.

Catalog loaders now use small, typed parsing and pagination helpers. They retain
raw-row offsets, primary-credit filtering, last simplified record per ID, original
request order, fallback details, raw top-track ranks and tolerant metadata. All
nineteen new observation tests pass both against the pre-extraction loader code
from `6ecbb96` and against the refactored implementation. No frozen fixtures changed.

The routine's public entry signatures remain intact and delegate composition to
bootstrap. Public boundary docstrings now describe their parameters, results and
errors. New Kids contains no lambdas or nested function definitions; the original
history refresh, error translation, clock and versioned JSON boundaries remain.

- Full suite: **2,294 tests pass**, seed `20260944`; **92.51% statements**
  (19,256 / 20,816) and **80.66% branches** (4,259 / 5,280).
- Independent gates: **243 domain tests**, **563 application tests**, with
  **100% statement and branch coverage** for configured targets.
- Seven new actual CLI/HTTP tests exercise both discovery workflows, preview and
  real execution, choice validation, and restart after an accepted replacement.
  Their workers use simulated Spotify/Last.fm and isolated files/state.
- All eleven frozen interface artifacts, existing characterization traces,
  package lint/format/mypy and strict inner-layer checks pass.

This completes the New Kids/Queue 2 migration within release progression. Queue 3
and the remaining Item 6 waves are still pending; the milestone has no PR yet.

### Queue 3 annual import checkpoint

Annual source selection now lives in the domain: yearly titles match exactly
apart from case, duplicate source IDs collapse in observation order, and the
first marker for each primary artist wins without track-ID deduplication.
The injected application workflow owns import decisions and accepted-effect
ordering; Spotify batches, translated read errors, audit storage and messages
remain at their original boundaries.

The seven new failure/projection tests passed against the original implementation
before extraction. They preserve the important recovery distinction: additions
precede every audit, all audits precede working-list extension, and working state
is marked complete before its checkpoint. Previews still audit and project markers
without remote writes or completion records. Completed yearly records suppress
source resolution, including during previews. Empty sources still complete.

- Full suite: **2,329 tests pass**, seed `20260945`; **92.54% statements**
  (19,339 / 20,897), **80.77% branches** (4,271 / 5,288).
- An additional source-error translation test passes with the other seven import
  boundary tests after the full run.
- Independent gates: **252 domain tests**, **582 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen interface artifacts, package lint/format/mypy and strict
  inner-layer checks pass. No frozen fixtures were changed.

Queue 3's standalone import entry, planning and flush coordination remain in
progress. This is an internal Item 6 checkpoint, not a completed roadmap item.
