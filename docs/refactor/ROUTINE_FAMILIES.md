# Item 6: routine family migration

**Status:** in progress on `codex/refactor-06-routine-families`, based on item 5's
merge `3d7c1df`. This document records checkpoints, not completion of item 6.
The full milestone remains one PR under the approved roadmap.

## Wave inventory

| Wave | Status | Destinations |
| --- | --- | --- |
| Foundation | Implemented and verified | Album review/recovery and artist-follow use cases in `application`; date policy in `domain`; explicit wiring in `bootstrap`; presentation and legacy integration adapters. |
| Release progression | Implemented and verified | Composer matching/observations, Slow Listening, New Wine, New Kids/Queue 2, Queue 3 and shared Requeue catalog integration. |
| History and discovery | In progress | History, radio, discovery, releases, The Queue and genre workflows. |
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

### Queue 3 standalone import and chronological planner checkpoint

The standalone annual-import entry now delegates composition to bootstrap and
summary decisions to the application layer. Four new tests passed against the
original entry before extraction, preserving playlist observations before state
loading, preview cloning, completed-year short circuits and progress ordering.

Chronological planning now uses injected track reads and live evaluations, the
existing independent release ordering policy, and the caller's original caches.
Within-release advancement, unmapped marker recovery, ineligible sources, final
completion, and prompted transitions preserve their durable plan fields. Empty
track observations remain cached. Equal-date ordering checkpoints still precede
the operator's transition prompt; quitting suppresses target-track observation.
Eleven new planner contracts passed against the original implementation before
extraction and continue to pass unchanged.

- Full suite: **2,371 tests pass**, seed `20260946`; **92.60% statements**
  (19,438 / 20,991), **80.96% branches** (4,278 / 5,284).
- Independent gates: **255 domain tests**, **605 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen interface artifacts, package lint/format/mypy and strict
  inner-layer checks pass. No frozen fixtures were changed.

Composer routing and Queue 3 restart/flush coordination remain in progress, as do
the later Item 6 waves. This checkpoint does not open the milestone PR.

### Queue 3 composer routing and durable records checkpoint

Composer route selection and works-playlist plans now have application owners.
They preserve ID-first matching, unique token-normalized title fallback, repeated
source-ID skipping, and the original skip/complete/advance plan fields. Valid
saved routes remain untouched. Stale routes are removed before ambiguous choices,
cancellation or errors; accepted routes alone read a new timestamp.

Queue 3 snapshots and record reconstruction are independent of Spotify and storage.
The snapshot deliberately retains its last-valid-route-wins rule, separate run-ID
and creation clock reads, original first-ten-logical-artists selection, and source
serialization order. Record decoding keeps original constructor failures, string
coercions, optional evaluations, unknown actions and public result labels. Twelve
new composer/snapshot contracts passed before extraction and remain unchanged.

- Full suite: **2,419 tests pass**, seed `20260947`; **92.67% statements**
  (19,513 / 21,056), **81.23% branches** (4,302 / 5,296).
- Independent gates: **255 domain tests**, **641 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen interface artifacts, package lint/format/mypy and strict
  application checks pass. No frozen fixtures were changed.

Queue 3 execution and restart coordination remain in progress. Six additional
execution-boundary tests have passed against the current coordinator before its
extraction; they are the next checkpoint's preparation, not a completed migration.

### Queue 3 saved-plan execution checkpoint

Saved-plan execution now decodes the original records, invokes the shared library
reconciler, and applies playlist effects through injected boundaries. Library
reconciliation still precedes marker-presence validation. Add/message/remove/
message ordering, preview projections, composer-only source cleanup and the fixed
original marker snapshot are unchanged. Audit and acknowledgment remain owned by
the coordinator for its subsequent extraction.

Seven new recovery contracts pass both against the coordinator from `554a2a9`
and the extracted executor. These include an existing edge case: ordinary
same-artist cleanup can remove an already-present replacement from the observed
snapshot on resume. The refactor deliberately preserves that behavior. Likewise,
fallback source-URI removal retains the original live-ID projection selection.
These are documented compatibility behaviors, not fixes in this milestone.

- Full suite: **2,457 tests pass**, seed `20260948`; **92.68% statements**
  (19,587 / 21,134), **81.51% branches** (4,325 / 5,306).
- Independent gates: **255 domain tests**, **673 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen interface artifacts, package lint/format/mypy and strict
  application checks pass. No frozen fixtures were changed.
- Five further coordinator preparation tests verify resumed container validation
  and already-acknowledged entries before the remaining orchestration moves.

Queue 3 restart and review coordination remain in progress. Item 6 is not yet
complete and has no PR or deployment.


### Queue 3 coordination and shared catalog checkpoint

Queue 3 restart and review coordination now belong to independent application
services. Saved plan validation, stale composer route replacement, audit before
acknowledgment, pause/resume and completion checkpoints retain their original
ordering. Thirty-six independent coordination tests cover these decisions; six
real CLI/HTTP tests exercise annual imports and release choices in preview and
write modes.

Slow Listening, Queue 3 and Requeue share the studio catalog adapter through
compatible public entry points. Candidate conversion belongs to the domain;
observations and existing error translations remain at the infrastructure
boundary. Three additional adapter tests preserve the distinct exception chains.

- Full suite: **2,507 tests pass**, seed `20260951`; **92.86% statements**
  (19,746 / 21,265), **82.06% branches** (4,359 / 5,312).
- Independent gates: **256 domain tests**, **710 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen interface artifacts, package lint/format/mypy (201 source
  files) and strict inner-layer checks pass. No frozen fixtures were changed.
- The three additional infrastructure error-chain tests pass after the full run.

The release-progression wave is implemented and verified. History and discovery
is next; Item 6 remains in progress with no PR or deployment.

### Canonical history refresh orchestration checkpoint

Canonical history refresh now has an independent application workflow with
explicit storage, live-read, clock, cancellation and presentation boundaries.
It retains occurrence-count overlap rather than set deduplication, stable ordering
for equal timestamps, original metadata, rebuild deletion semantics, fallback
backups, and the refusal to replace nonempty history with an empty API response.
Live record conversion remains after the post-request cancellation check.

Eight new failure-order contracts passed against the original workflow before
extraction. Hydration still precedes cancellation; backup precedes replacement;
check-time marking precedes managed publication and final audit. Successful
unchanged checks still publish managed history. Preview still hydrates and reads,
but suppresses persistence. Existing file parsers and serialization helpers remain
behind the compatibility adapter for the subsequent infrastructure cleanup.

- Full suite: **2,544 tests pass**, seed `20260952`; **92.88% statements**
  (19,842 / 21,362), **82.07% branches** (4,358 / 5,310).
- **24 independent refresh tests** cover all statements and branches in the new
  application workflow and values. The complete application gate passes
  **736 tests**, with **100% statements and branches** across configured targets.
- Six additional real CLI/HTTP history tests pass after the full suite, covering
  incremental/rebuild persistence and previews through actual command workers.
- All eleven frozen interface artifacts, package Ruff formatting/lint, package
  mypy (205 source files) and strict application checks pass.

History/discovery migration continues; this checkpoint does not complete Item 6
or open its milestone PR.

### Historical track selection and playlist checkpoint

Friday date selection, anniversary selection, shared match resolution and both
playlist coordinators now have independent application owners. Anniversary year
spacing and leap-date handling belong to the domain, alongside title similarity,
liked-status album overrides and match ranking. Existing public values are
re-exported from their original routine modules.

Twenty-two new observation/failure contracts passed against the original playlist
and resolution functions before extraction. Friday still observes capacity before
history selection; radio still selects first and skips Spotify for empty targets.
Missing anniversary dates retain their original selection indexes. All searches
precede the shared liked-status observation. Existing membership precedes pending
batch duplicate detection; previews retain resolved `added` actions while their
projected length excludes writes. Original synchronous parsing, batching, retry
and Random.org helpers remain behind the compatibility adapters for later cleanup.

- Full suite: **2,664 tests pass**, seed `20261002`; **93.02% statements**
  (20,041 / 21,544), **82.43% branches** (4,367 / 5,298).
- Independent gates: **279 domain tests**, **799 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- Six actual CLI/HTTP tests exercise both workflows, including liked album
  overrides, repeated radio selections, accepted appends and previews.
- All eleven frozen interface artifacts, package Ruff formatting/lint, package
  mypy (212 source files) and strict inner-layer checks pass.
- The domain dependency allowlist now includes Python's pure `difflib` module for
  the existing sequence matcher; runtime and SDK imports remain prohibited.

Found Art and the remaining history/discovery routines are still pending.
Item 6 remains one ongoing milestone with no PR or deployment.


### Recommendation history and seed selection checkpoint

Found Art's normalized track identities, occurrence statistics, Friday date policy
and deterministic weekly ranking now belong to the domain. Local clock and Berlin
timezone resolution remain at the outer boundary. The original newest-input
recency anchor, inclusive 90/365-day windows, first-identity order and strictly
newer display replacement are preserved, including invalid newest identities.

Recent, annual and overall seed quotas now use short named popularity, weekly
ranking, acceptance and fallback stages. Artist caps, original pool limits,
source-specific weights and manually duplicated input tolerance are unchanged.
The independent application service validates counts before consuming history,
resolves a default week only after materialization, and retains original state
errors when there are too few diverse seeds.

Four history/rank contracts and seven exact seed snapshots passed against the
original code before extraction. The seed fixtures record source `f1704d0` and
include remainders, fallback, duplicates and diversity failures. Existing Found
Art, Sauvignon and The Queue tests continue to pass unchanged.

- Full suite: **2,722 tests pass**, seed `20261004`;
  **93.08% statements**
  (20,164 / 21,662),
  **82.59% branches**
  (4,392 / 5,318).
- Independent gates: **312 domain tests**, **813 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen interface artifacts, package Ruff formatting/lint, package
  mypy (217 source files) and strict inner-layer checks pass.
- Pure standard-library `hashlib` and `functools` are now permitted by the domain
  dependency check for the existing hashing and named sort-key binding.

Found Art candidate/cache handling and the remaining discovery workflows remain
in progress. This checkpoint does not complete Item 6 or open its milestone PR.

### Recommendation candidate gathering checkpoint

Found Art neighborhood observation and cache checkpoints now use an injected
application workflow. Candidate accumulation, distinct-seed support bonuses,
base pool limits and deterministic weekly rotation belong to the domain. The
Last.fm neighborhood value is shared through the existing client import alias.

Seven boundary tests passed against the original gatherer before extraction.
They preserve each failure boundary, cumulative checkpoints, empty current-week
cache hits and disabled audit exclusions. Fetches are still checkpointed before
aggregation or the next seed, including during preview runs. Existing cache
decoding and serialization remain behind the legacy adapter for a later slice.

- Full suite: **2,758 tests pass**, seed `20261005`;
  **93.12% statements** (20,253 / 21,749),
  **82.66% branches** (4,399 / 5,322).
- Independent gates: **318 domain tests**, **836 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen public interface artifacts, package Ruff lint/format,
  package mypy (220 source files) and strict inner-layer checks pass.

Found Art Spotify resolution, full-run orchestration and storage ownership
remain pending. Item 6 continues as one milestone without a PR or deployment.

### Recommendation resolution and full-run checkpoint

Found Art's liked/unliked preference and ordered artist, membership, duplicate
and capacity decisions now belong to the domain. The application observes whole
search batches before reading liked status and projecting results. Its distinct
ranking still ignores album similarity, and any liked match suppresses additions.
Known artist/key exclusions skip searches while retaining empty liked groups.

The injected full-run coordinator refreshes canonical history before observing
destination capacity, then selects seeds, gathers cached neighborhoods, resolves
matches, appends pending tracks and audits the completed summary. Full playlists
still refresh history and audit; previews retain history, cache and audit effects.
The existing models and routine functions remain available as compatibility aliases
and facades.

Nine matching and twelve full-run boundary tests passed against the original code
before their respective extractions. Four actual CLI/HTTP tests execute the full
migrated path with deterministic clocks, simulated clients and isolated files.
They verify live liked exclusions, accepted appends, preview cache/audit writes
and empty neighborhood checkpoints.

- Full suite: **2,837 tests pass**, seed `20261006`;
  **93.18% statements** (20,389 / 21,882),
  **82.79% branches** (4,406 / 5,322).
- Independent gates: **328 domain tests**, **880 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen public artifacts, package Ruff lint/format, package mypy
  (223 source files) and strict inner-layer checks pass.

Found Art cache/audit codecs and storage ownership still remain at legacy seams.
The remaining history/discovery routines and later waves remain pending; this
checkpoint does not complete Item 6 or open its milestone PR.

### Recommendation storage checkpoint

Found Art cache loading, tolerant neighborhood decoding, atomic checkpoints,
prior-addition parsing and append-only audit serialization now have an
infrastructure owner. The routine retains typed compatibility facades. Codecs
use short named helpers and preserve original JSON field order, Unicode, omitted
internal fields, physical-line diagnostics, exception causes and partial-write
artifacts.

Thirty-three new storage contracts passed against the original code before
extraction. A new byte snapshot records source `e8b4df4`; all earlier frozen
fixtures remain unchanged. Two repeated CLI tests also passed with the original
decoder loaded in memory before verifying the extracted decoder. They protect
valid current-week cache reuse, injected timestamp constructor semantics and
the distinction between actual prior additions and preview proposals.

- Full suite: **2,872 tests pass**, seed `20261007`;
  **93.19% statements** (20,443 / 21,938),
  **82.81% branches** (4,412 / 5,328).
- Focused storage and real interface checks: **65 tests pass** with
  **100% statement and branch coverage** for the storage module.
- The independent inner-layer gates remain **328 domain tests** and
  **880 application tests**, both at 100% for configured targets.
- All eleven frozen public artifacts, package Ruff lint/format, package mypy
  (224 source files), strict inner-layer checks and strict storage/boundary test
  checks pass. Six real CLI/HTTP cases exercise the complete Found Art path.

Found Art policy, application coordination and storage extraction is implemented
and verified. Sauvignon and the remaining history/discovery routines are next.
Item 6 remains ongoing without its milestone PR or deployment.

### Sauvignon album evidence checkpoint

Sauvignon's album identities, heard-album filtering, edition preference, visible
metadata ambiguity and track-evidence accumulation now belong to the domain.
The application preserves sequential candidate progress and searches before
combining each observation. Spotify parsing and retry calls retain their existing
outer compatibility boundaries.

Nine new contracts passed against the original gatherer before extraction.
Five immutable scenarios record source `4e21c84`, original inputs, exact ranked
recommendations and progress/search traces. They cover grouped editions,
duplicate support labels, preferred edition replacement, exclusions, empty pools
and original negative-slice tolerance. Independent policy tests additionally
preserve invalid normalized observation keys, nullable accumulator behavior,
assertions after score updates and all visible ambiguity components.

- Full suite: **2,911 tests pass**, seed `20261008`;
  **93.21% statements** (20,502 / 21,996),
  **82.90% branches** (4,425 / 5,338).
- Independent gates: **346 domain tests**, **892 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- All eleven frozen public artifacts, package Ruff lint/format, package mypy
  (227 source files), strict inner-layer checks and strict fixture/contract checks
  pass. New functions remain short and flat with simple comprehensions.

Sauvignon's catalog parser, first-track observation, choice interaction, complete
run and audit ownership remain pending. Item 6 continues without a milestone PR,
local review environment, deployment or merge.

### Sauvignon catalog and edition choice checkpoint

Sauvignon's edition interaction now belongs to the application. Equivalent
visible editions choose the first observation automatically; ambiguous editions
retain the original single prompt, skip/quit markers, first matching identity
and invalid-response fallback. Eight contracts passed against the original
chooser before extraction, with independent interaction and error tests after it.

Album/first-track response parsing now has an infrastructure owner. Mandatory
artist/title matching remains first, exact primary track and album credits are
still required, and the shared domain release classifier applies the original
plain studio album/EP eligibility. Metadata coercion, preferred edition
deduplication, deterministic order and first playable track selection are
unchanged. The public models and errors retain compatibility aliases; synchronous
SDK expressions and retry descriptions remain at their existing routine seams.
Thirty new parsing contracts passed before moving those codecs.

- Full suite: **2,968 tests pass**, seed `20261009`;
  **93.24% statements** (20,560 / 22,050),
  **83.08% branches** (4,443 / 5,348).
- Independent gates: **354 domain tests**, **902 application tests**, both at
  **100% statement and branch coverage** for configured targets.
- The focused codec gate passes **48 tests** with **100% statement and branch
  coverage** for the new infrastructure module.
- All eleven frozen public artifacts, package Ruff lint/format, package mypy
  (229 source files), strict inner-layer and new boundary test checks pass.
  Ten migrated source/test files also pass the short, flat function check.

Sauvignon's complete run, live recheck/append and audit ownership remain pending.
Item 6 remains ongoing without a milestone PR, deployment or merge.

### Sauvignon full-run and audit checkpoint

Sauvignon now has an independent application coordinator for history refresh,
capacity, evidence gathering, edition interaction, first-track observations,
fresh membership checks, accepted appends and final audit. Ordered selection
retains artist and album uniqueness, skip/quit outcomes and the original
initial-size summary after fresh membership suppresses proposals. All selected
first tracks are observed before mutation. Accepted append, output and audit
remain sequential; a later failure preserves the original accepted-effect prefix.

Twenty-one additional full-run contracts and eleven storage contracts passed
before their respective extractions. The new immutable audit snapshot records
source `207c8e4`, exact JSON field order, omissions and trailing newline. The
infrastructure reader preserves tolerant non-added rows, string coercion and
physical-line diagnostics. Two actual repeated CLI runs verify history, cache,
catalog resolution, accepted-addition exclusions and preview audit semantics.

- Full randomized suite: **3,036 tests pass**, seed `20261011`;
  **93.37% statements** (20,742 / 22,216),
  **83.30% branches** (4,465 / 5,360).
- Independent gates: **357 domain tests**, **933 application tests**, both with
  **100% statement and branch coverage** for configured targets.
- Focused Sauvignon run, selection, values and storage: **42 tests**, **100%**
  statement and branch coverage (237 statements, 54 branches).
- All eleven frozen public artifacts, package Ruff/format, package mypy
  (235 source files), and strict new source/test checks pass.

The remaining history/discovery workflows and later waves are still part of
Item 6. Work continues on this branch toward its single complete milestone PR.

### Dormant-artist recovery checkpoint

Dormant recovery now owns its rolling intersection and preferred liked-track
policies in the domain. The application observes top tracks and live membership
first, then reads the primary-credit catalog and popularity only when needed.
The complete recovery coordinator preserves original alphabetical selection,
full-list mapping ranks, represented-artists suppression, cancellation before
represented checks, skip output, duplicate-marker suppression and one ordered
batch append before completion progress. Preview results intentionally retain
original `added` labels while playlist size reflects no remote write.

Ten new routine contracts passed against source `496f3d5` before extraction,
covering every original failure prefix and accepted-write/preview behavior.
Independent workflow and policy tests cover all new inner-layer statements and
branches. The shared observed artist-mapping value has a domain owner with a
public compatibility alias in release checking. Infrastructure codecs retain
original truthiness, response cardinality, duplicate detail order, coercion and
boolean integer popularity tolerance. Original SDK expressions remain frozen.

- Full suite: **3,088 tests pass**, seed `20261012`;
  **93.42% statements** (20,879 / 22,349),
  **83.41% branches** (4,481 / 5,372).
- Independent gates: **366 domain tests**, **955 application tests**, both with
  **100% statement and branch coverage** for configured targets.
- Focused new policy/workflow gate: **25 tests**, **100%** statement and branch
  coverage (157 statements, 42 branches). Infrastructure codec gate: **11 tests**,
  **100%** (28 statements, 14 branches).
- All eleven frozen public artifacts, package Ruff/format, package mypy
  (243 source files), strict new source/test checks and short-function checks pass.

Release checking, The Queue and genre reveal remain in the current wave. Later
waves retain their full approved scope. Item 6 continues toward its single PR.

### Release policy and artist-mapping checkpoint

Release-check models, global artist ranking, majority display spelling,
release-kind inference, partial-date windows, title/rank exclusions, review tags
and destination identity/deduplication rules now have domain owners. The original
artist interaction belongs to the application: only an initial unique exact match
is automatic; custom queries remain trimmed, repeatable and explicitly prompted.
Original controls, exact-only initial prompt lists, first matching identity and
narrowed validation errors are retained. Public routine models/errors remain
aliases. Run coordination, catalog paging and durable state still remain next.

An immutable policy snapshot records 105 cases against source `2fdcd9e` before
extraction. Eleven additional original interaction contracts also passed before
moving the chooser. Independent tests replay the same policy/interaction oracles
and protect ranking, destination membership and original preview summary counts.
The domain import gate explicitly allows Python's pure `calendar` utility for
original partial-month precision; runtime/client/UI prohibitions remain intact.

- Full suite: **3,332 tests pass**, seed `20261013`;
  **93.52% statements** (20,997 / 22,451),
  **83.76% branches** (4,503 / 5,376).
- Independent gates: **480 domain tests**, **969 application tests**, both with
  **100% statement and branch coverage** for configured targets.
- Focused policy gate: **112 tests**, **100%** (156 statements, 50 branches).
  Focused interaction/summary gate: **12 tests**, **100%** (61 statements,
  18 branches).
- All eleven frozen public artifacts, package Ruff/format, package mypy
  (248 source files), strict new source/test and short-function checks pass.

Item 6 continues with release catalog ownership and complete restartable run
coordination, followed by the remaining approved families. No milestone PR is
opened until the full Item 6 exit criteria are met.

### Release catalog decoding and future-record checkpoint

Release-check artist, release and track metadata now have an infrastructure
codec owner. Original required fields, first-credit checks, metadata coercion,
blank display-name tolerance, precision spelling, zero/invalid position fallback
and undeduplicated raw search ranks are unchanged. Public helpers remain typed
compatibility facades around the original synchronous SDK/retry expressions.

Future-record matching belongs to the application and independent title/ID
policies. Records are observed in original order, caller-owned empty cache hits
are retained, accepted reads are cached before matching, and failure on a later
read preserves earlier cache entries. Exact ID and nonempty qualifier-tolerant
title matches retain original first-record preference and credit tolerance.

Seventy-four codec scenarios were frozen against the original decoders before
moving them; the immutable snapshot records source `2fdcd9e`. Six original
future-record contracts passed before extraction and are replayed independently.
Additional codec checks protect malformed search envelopes, skipped raw ranks,
duplicate observations and ID-fallback versus blank-name behavior.

- Full suite: **3,502 tests pass**, seed `20261014`;
  **93.58% statements** (21,060 / 22,504),
  **84.03% branches** (4,521 / 5,380).
- Independent gates: **481 domain tests**, **976 application tests**, both with
  **100% statement and branch coverage** for configured targets.
- Focused policy, future-record and codec gate: **201 tests**, **100%** statement
  and branch coverage (224 statements, 90 branches).
- All eleven frozen public artifacts, package Ruff/format, package mypy
  (251 source files), strict new source/test and short-function checks pass.

Complete release-check run/checkpoint coordination, catalog paging and durable
state ownership are next. Remaining waves stay in scope for the Item 6 PR.

### Retry configuration order follow-up

An additional Sauvignon boundary test detected that outer composition evaluated
a supplied falsey retry callable before request validation. The frozen original
runner at `207c8e4` was executed offline to confirm validation must happen first.
Retry fallback resolution now occurs once after application validation and before
clock/history observation, preserving the original order without duplicate
validation or an extra application lifecycle abstraction. Invalid-request and
valid-run regressions, the prior failure-prefix suite and actual CLI checks pass
(**54 focused tests**). Package mypy and strict new contract checks pass.

### Release-check opening checkpoint

The application now owns opening a new run or resuming its frozen ranking and
window. The outer adapter retains the clock, history configuration, original
state handle and audit seams. Preview runs still refresh history for real;
resumed runs do not refresh it. New runs checkpoint before the started event.
Unknown state fields and the original previous-date/year-start rule are retained.

Nine contracts ran against the original opening before extraction. Twenty-two
independent application cases protect window boundaries, resume authority,
observation order and accepted-write failure prefixes. The new coordinator has
100% statement and branch coverage (68 statements, 8 branches). Domain and
application gates pass independently: 481 and 999 tests respectively, both at
100% statement/branch coverage. Package Ruff, formatting and mypy pass; all 11
frozen public artifacts match. The randomized complete suite passes 3,536 tests
(seed 20261015). This checkpoint also includes the Sauvignon validation/retry
ordering correction verified against the original runner.

The release-check review, mutation and checkpoint stages and the remaining Item 6
families still need migration before the milestone PR is ready.

### Release-check complete coordinator checkpoint

The release workflow now has independent stages for destination cleanup, artist
mapping/exclusion, catalog edition selection, release review, ordered playlist
writes and durable progress. The compatibility entry point composes those stages
with the original synchronous SDK and persistence seams. No SDK operation or
public interface changed. The main runner no longer embeds a 600-line review loop.

Before extraction, 43 complete-run and accepted-effect failure scenarios were
captured from source `979330d` in `tests/fixtures/refactor/release_run.json`.
Those immutable observations cover mapping/skip/quit behavior, preview learning,
composer and membership exclusions, market editions, processed/pending releases,
single containment, invalid choices and accepted-write failure prefixes. Both the
compatibility runner and the independent application workflow match every trace,
checkpoint and result. Additional tests protect numeric checkpoint boundaries,
malformed progress, retrieving all sections before type assertions, pending
ownership, missing catalog records, unavailable single markers, cleanup audits,
and defaults without a review callback.

The extracted stages and catalog policies reach 100% statement and branch
coverage (417 statements, 128 branches). Isolated domain and application gates
pass 488 and 1,070 tests at 100% statement/branch coverage. Package Ruff, formatting
and mypy pass (264 source files); short-function checks pass for new code, and all
11 frozen public artifacts match. The complete randomized suite passes 3,657
tests with seed 20261016. Release paging/storage boundary ownership remains to
finish before moving on to The Queue, genre reveal and the later approved waves.
Item 6 remains in progress; this checkpoint does not open its milestone PR.

### Release-check paging and restart decoding checkpoint

Catalog, marker and destination pagination now have explicit infrastructure owners,
with distinct original stopping and failure rules. SDK expressions and their retry
configuration remain in the original outer module. Catalog reads continue past
old pages; later duplicate identities replace metadata. First-only marker reads
stop after one page, and a 404 on any marker page discards earlier markers.
Destination reads follow continuation or integer totals and reject any item that
cannot be safely retained. These behaviors are preserved, including their quirks.

Restart decoding now owns additive legacy defaults, unknown-field preservation,
frozen artist restoration, mappings and retained singles at a documented JSON
boundary. Constructor field values retain the original tolerance; the codecs do
not silently impose stronger value validation. Result construction delegates to
the shared application owner.

Twenty-six paging and 32 restart cases pass both against the original source
(`91a502a`, replayed offline without changing the checkout) and the new owners.
The owners reach 100% statement/branch coverage (127 statements, 40 branches).
All 11 frozen public artifacts match, including identical SDK expressions,
reference counts and source paths. Ruff, formatting, package mypy and strict new
boundary/test typing pass. The complete randomized suite passes 3,715 tests
(seed 20261017). The next history/discovery migrations are The Queue and genre
reveal; the approved later waves remain part of the same Item 6 milestone.

### Genre reveal workflow and route checkpoint

Genre reveal now separates pure route/slug/display/membership policies, public
source and route codecs, Pydantic boundary contracts, the ordered save/copy/audit
workflow and idempotent progress replacement. The synchronous public-page reader
and original SDK expressions remain at the outer compatibility boundary.
Callbacks and result presentation retain their original seams. Google-style
engineering docs are independent of explicitly frozen Pydantic schema descriptions,
so every published HTTP schema remains identical.

Nine effect-order/failure contracts passed against original source `98531c0`
before migration and still pass. Independent workflow cases reproduce those
prefixes without SDK, filesystem or startup dependencies. Four actual CLI/HTTP
cases exercise public-page decoding, membership, accepted writes, audit and state
completion using offline transport boundaries. Failed accepted appends retain
Spotify effects while leaving progress incomplete and producing no completion
audit. Identical progress updates preserve existing metadata and perform no save;
changed fields preserve route order and clock/read/save ordering.

Domain/application policies and workflows have 100% statement/branch coverage;
source/model codecs also have 100% coverage (96 statements, 18 branches). Domain
and application gates pass 508 and 1,086 tests independently, both at 100%.
Package Ruff, formatting and mypy pass (276 source files), strict new test typing
passes, new functions satisfy the short/flat rules and contain no multiline list
comprehensions. All 11 frozen public artifacts match. The randomized full suite
passes 3,783 tests (seed 20261018). The Queue and the approved deep-listening,
library and operational waves still remain before the complete Item 6 PR.

### Queue history and seed selection checkpoint

History counts, inclusive recent/annual cutoffs, display spelling and weekly
quota/fallback selection now have domain owners. The application validates the
request before consuming history and resolves the week only after checking
availability. Compatibility models and error identities remain unchanged.

Eighty-six frozen scenarios passed against the original implementation before
extraction. Forty-eight independent policy/application cases cover valid results
and validation observation order. These owners have 100% statement/branch
coverage (131 statements, 40 branches). The isolated domain and application gates
pass 555 and 1,092 tests, respectively, at 100% coverage. Ruff, formatting, package
mypy and all 11 frozen public artifacts pass. The full randomized suite passes
3,922 tests (seed 20261019), with 94.00% statements and 85.28% branches.

Recommendation aggregation, fill and restartable flush remain in progress, as do
the later approved waves. This checkpoint does not complete Item 6.

### Queue artist recommendations and cache checkpoint

Artist-neighborhood aggregation and weekly rotation now have a domain owner;
the application owns ordered progress, current-week cache lookup, Last.fm reads
and immediate cache acceptance before aggregation. Boundary codecs retain naive
UTC timestamps, skipped nonrecord rows, permissive field conversion and actual
addition filtering. Valid empty neighborhoods remain cache hits. Zero and
negative candidate limits retain original slice behavior and still gather seeds.

Fourteen ranking/cache observations were frozen and passed before extraction.
Twenty-nine independent domain/application cases cover original results and
accepted-effect failure prefixes. Sixteen boundary cases protect cache and log
decoding. These owners have 100% statement/branch coverage (120 statements,
28 branches). Isolated gates pass 571 domain and 1,107 application tests at 100%.
Package Ruff, formatting and mypy pass; all 11 frozen public artifacts match.
The Queue fill and restartable flush and the later approved waves remain pending.

The full randomized recommendation checkpoint passes 3,983 tests with seed
20261020 (94.03% statements, 85.34% branches).

### Queue fill workflow checkpoint

Queue fill now separates request validation, history/capacity facts, seed and
candidate gathering, mapping interaction, marker selection and ordered execution.
Accepted mapping checkpoints still occur during preview runs. Follow, artist
mirror persistence, playlist append, audit and presentation retain their original
order and failure boundaries. Original configured limits remain composed at the
edge. No-capacity runs still refresh history and read Queue membership before
returning without seeds, cache, representations or state.

Thirty-two complete-run/failure observations passed against the original source
before extraction. The independent application reproduces every result, trace,
state and checkpoint. Additional cases protect guards before retry configuration,
capacity exits, saved mappings, duplicate representations and stopping before the
next progress callback. Domain/application owners reach 100% statement/branch
coverage (150 statements, 42 branches). Isolated gates pass 581 domain and 1,151
application tests at 100%. Ruff, formatting, package and strict new test typing
pass. New functions are short and contain no nested definitions or multiline
list comprehensions. All 11 frozen public artifacts match.

Restartable Queue flush and the later approved waves remain pending.

The full randomized fill checkpoint passes 4,069 tests with seed 20261021
(94.08% statements, 85.42% branches).

### Queue restartable flush checkpoint

The application now owns opening/resuming daily snapshots, durable plan
acceptance, ordered destination effects, source removal, completion audits and
entry/final checkpoints. Pure policies own distinct-artist daily selection and
the original live membership rules. Tolerant stored-record constructors have an
infrastructure owner. The shared Queue state port is independent of either fill
or flush. Original SDK expressions and callable compatibility seams remain at
the outer boundary.

Fifty-eight complete observations passed against the original runner before
extraction. Eight additional indexed checkpoint/progress failures and 14 resumed
executions were captured by replaying trusted pre-extraction source `4489fa3`
offline, without changing the checkout. Independent application runs match every
trace, result, checkpoint and live membership. Stored plans retain authority;
unknown actions retain original tolerance. Preview runs still audit completions.
First-initial-URI identity removal and zero daily-limit behavior are preserved.

The coordinator, effects and membership policies have 100% statement/branch
coverage (191 statements, 76 branches). Twenty-six boundary cases cover stored
records at 100% coverage (45 statements, 12 branches). Isolated gates pass 588
domain and 1,238 application tests at 100%. Ruff, formatting, package mypy and
strict new test typing pass; short/flat structure checks pass. All 11 frozen
public artifacts match. The full randomized suite passes 4,255 tests with seed
20261022 (94.17% statements, 85.78% branches).

Live flush planning and its promotion-marker reads remain to finish, followed by
the later approved deep-listening, library and operational waves. Item 6 remains
in progress until every approved wave is accounted for.

### Queue live planning checkpoint

Pure Queue decisions now own advancement cursors, the six-catalog/five-top
promotion thresholds, rejection reasons and missing-promotion blocking. The
application gathers top tracks, liked status, ranked catalog and the shared
artist assessment in original order, then resolves the first preferred primary
marker using the original run-scoped cache. Original configured limits and
compatibility seams remain at the edge. Queue's business stages are now separated;
the compatibility module has only short helpers and delegates its workflows.

One hundred forty-four original threshold/cursor/cache combinations passed before
extraction. Both independent domain and application scenarios match every plan
and ordered read trace. These owners reach 100% statement/branch coverage
(78 statements, 28 branches). Isolated gates pass 734 domain and 1,383 application
tests at 100%. Ruff, formatting, package mypy and strict new test typing pass.
Structure checks find no long functions, nested definitions or multiline list
comprehensions in new planning code. All 11 frozen public artifacts match.

The next approved wave covers Something Old, Palace of Memory, Discography and
New Year, followed by library/legacy and operational integration. Item 6 is not
complete until those waves and the final ownership audit pass.

The full randomized Queue planning checkpoint passes 4,690 tests with seed
20261023 (94.21% statements, 85.90% branches).

### Something Old checkpoint

Golden Oldies now has pure owners for exact-label history aggregation, oldest
average ranking, exact normalized Spotify artist qualification and the three
marker recipes. The application coordinates initial empty-playlist authority,
history refresh, interaction, cancellation, the final live empty check, append
and completion audit. Catalog parsing and JSON Lines audit bytes have outer
owners. Original public model and error identities remain compatibility aliases;
original SDK expressions remain at their frozen source paths.

Eleven immutable original history profiles, 53 complete original runner
observations and 41 original raw artist/popular-track boundary observations were
captured before their extraction. Independent injected execution matches every
complete summary and failure prefix. Exact trimmed history spelling remains
distinct; artist and title ties, integer average dates and the inclusive 50-play
threshold are unchanged. Every Last.fm title is searched before the single liked
read. Popular tracks accept any matching artist credit and stop parsing at ten
distinct identities. Album choices retain complete uncapped tracklists. Writes
still follow the original live recheck without introducing new mutation retries.

The isolated gates pass 761 domain and 1,489 application tests with 100% statement
and branch coverage. The new selection policies, coordinator and tolerant catalog
codecs also reach 100% individually. Ruff, formatting, package typing and strict
inner-layer typing pass. All 11 frozen public artifacts match. The full randomized
suite passes 4,887 tests with seed 20261024 (94.31% statements, 86.24% branches).

Palace of Memory, Discography, New Year, library/legacy and operational integration
remain to finish before the complete Item 6 pull request is opened.

### Palace of Memory checkpoint

Palace now separates alphabetical and historical selection, saved-edition matching,
first-marker qualification and membership classification from its ordered runner.
Named application owners coordinate live mirror refresh, historical date selection,
manual cursor updates and completion. Catalog records, cursor files, mirror
publication and audit bytes have infrastructure owners. The original facade keeps
caller seams, public model/error identities and frozen SDK expressions.

Before extraction, immutable observations captured 33 complete runs, five accepted
effect/restart scenarios, 120 historical selections, 12 mirror refreshes, ten cursor
updates and 45 raw catalog boundaries. Injected execution matches these traces,
including mirror publication during preview, the final live membership recheck,
first-track cache reuse, repeated unsaved search reads, independent cursor clocks
and audit ordering. Mirror failures retain the original replacement/backup effects;
failed cursor writes retain their temporary files.

Isolated gates pass 785 domain and 1,676 application tests at 100% statement and
branch coverage. The final coordinator completion stage also reaches 100% in its
38 focused scenarios. Ruff, formatting, package mypy and strict new boundary
typing pass. All 11 frozen public artifacts match. The complete randomized suite
passes 5,226 tests with seed 20261026 (94.66% statements, 87.14% branches).

Discography, New Year, library/legacy and operational integration remain before
the final Item 6 ownership audit and complete pull request.

### Discography checkpoint

Discography now has pure owners for independent queue-priority rotations, catalog
and marker qualification, edition chronology, historical artist rankings and
release-index expressions. Named application stages own ordered queue gathering,
complete paged catalog/saved-membership reads, lazy historical fallback, interactive
selection, round-week packing and confirmed execution. Shared studio parsing has
an infrastructure owner; Discography no longer imports Slow Listening's private
business helpers. State and audit files retain their original outer semantics.

Immutable original evidence covers 53 complete planning observations, 60 confirmed
execution/failure/replay observations, 44 raw catalog records, nine complete
catalog read profiles, 24 history/random selections, 15 source queue reads and
seven display-spelling rankings. Injected plans and execution preserve every
captured outcome and trace. Empty catalog/choice cache hits remain authoritative;
Memory Lane fallback stays lazy. Silent default counts qualify packing before
interaction, with no new constraint on the chosen count. Queue 3 removal still
requires Newfoundland markers. Every artist audit precedes the single final
priority checkpoint, including the original checkpoint on an empty plan.

Isolated gates pass 835 domain and 1,832 application tests at 100% statement and
branch coverage. New catalog/state/studio record boundaries reach 100% in 104
focused tests. Ruff, formatting, package mypy, strict new boundary/test typing and
structure checks pass. All 11 frozen public artifacts match. The full randomized
suite passes 5,523 tests with seed 20261027 (94.89% statements, 87.84% branches).

New Year, library/legacy and operational integration remain before Item 6 is
complete and its pull request is opened.
