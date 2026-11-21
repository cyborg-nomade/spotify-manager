# ADR 005: Apply current community tags with explicit unknown coverage

**Status:** Accepted; Tag Atlas approved, deployed and verified on 21 November 2026.
**Date:** 21 November 2026.

## Context

Library Bridge is deployed and merged. The next enrichment view should explain
how community labels relate to recorded listening over time. Scrobbles contain
no historical genres. Public tags can be missing, ambiguous, mutable, or unrelated
to genre; treating them as historical facts would misrepresent the evidence.

## Decision

Rendering uses cached observations only. An authenticated explicit POST selects
at most fifty highest-play missing or thirty-day-old artist observations from
one pinned history selection. The existing optional Last.fm key reads the fixed
`artist.getTopTags` endpoint with autocorrection disabled. Only the artist name
and API credential leave the application; listening records and usernames are
not sent. Requests run sequentially, separated by at least one second, with a
fifteen-second timeout, one-MiB response limit, and no implicit retries. A global
provider failure stops the batch and retains completed observations.

Accept source labels only when the returned artist agrees with the requested
NFC, trimmed, case-folded identity. Preserve accents and punctuation. Unknown
artists and identity disagreements remain unresolved. Verified empty labels,
unresolved identity, and artists never looked up are separate coverage outcomes.
Keep at most ten ranked unique labels; do not infer a genre taxonomy or interpret
provider popularity scores as listening weights. Credit and link to Last.fm.

Allocate each artist's recorded plays to either its leading label or equally
among up to three leading labels. Show eight leading labels, Other, and Unknown
in monthly buckets. Each selected recorded play contributes exactly one unit
across these categories; fractional allocations are labeled explicitly. Coverage
uses actual selected plays and artists before evidence/search filters. Current
labels applied to earlier plays do not establish historical genres or moods.

A named application stage owns one batch and calls its source/cache resources
directly. Concrete blocking provider reads and SQLite commits use the existing
bounded worker resource; cancellation drains an active operation. Completed
atomic cache commits remain counted after cancellation. Shutdown closes jobs,
then tag enrichment, collection reads, and the history runtime.

Keep the fixed derived SQLite cache outside canonical data and routine state.
The cache holds at most twenty thousand observations, evicting oldest retrievals,
and retains two immutable in-memory generations. A separate `t1-` content token
pins metadata independently of the history token. Expired tag versions return
409 with `X-Listening-Conflict: tags`; the browser retries metadata independently.
Cache or provider failures preserve history views. The default cache is under
the system temporary directory and survives process restart while its files
remain; operators may select an app-owned persistent directory. A reset requires
explicit new lookup batches and never rewrites history.

## Alternatives and consequences

Automatic lookups on page load would obscure provider activity and couple
historical exploration to network availability. A curated genre taxonomy or
fuzzy artist resolution needs separately reviewed evidence rules. Historical
tag snapshots are unavailable from the scrobble export. The explicit cache and
coverage model offers a useful comparison without asserting those missing facts.

Artist-name collisions can remain even after name corroboration. Retrieval dates,
ranked original labels, lookup outcomes, source links, and both version tokens
remain visible and exportable. A single process owns each cache directory;
multi-process deployments must give each process its own directory.

Provider contract: [artist.getTopTags](https://www.last.fm/api/show/artist.getTopTags),
[Last.fm API terms](https://www.last.fm/api/tos).
