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
