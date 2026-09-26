# Item 6: routine family migration

**Status:** in progress on `codex/refactor-06-routine-families`, based on item 5's
merge `3d7c1df`. This document records checkpoints, not completion of item 6.
The full milestone remains one PR under the approved roadmap.

## Wave inventory

| Wave | Status | Destinations |
| --- | --- | --- |
| Foundation | Implemented and verified | Album review/recovery and artist-follow use cases in `application`; date policy in `domain`; explicit wiring in `bootstrap`; presentation and legacy integration adapters. |
| Release progression | Pending | New Wine, Slow Listening, New Kids/Queue 2, composer playlists, Queue 3, shared Requeue integrations. |
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
