# ADR 004: Compare published collections using explicit name evidence

**Status:** Accepted; Library Bridge approved, deployed and verified on 21 November 2026.
**Date:** 20 November 2026.

## Context

The owner selected current-library comparisons as the next Listening Explorer
item. Last.fm observations lack verified Spotify identities. The existing durable
Spotify mirrors contain saved albums, liked tracks and followed artists, each
with an independent publication date. Artist names collide and release editions
often differ across services. Reading managed checkout mirrors would also risk
mixing locally edited or incompletely hydrated data with published history.

## Decision

Read all three collections through the existing durable service at one pinned
manifest revision. Verify each artifact's size and checksum into temporary files
before decoding it. Cache only complete decoded artifacts by checksum. A failed
artifact has unavailable coverage; a manifest conflict rejects the complete
attempt. An independent runtime retains two immutable collection generations,
uses at most one bounded background worker, and drains it during shutdown.

The analytical query pins both the existing history token and a separate
collection token. Collection membership describes the published collection,
regardless of the selected historical listening dates. No canonical files,
routine state, live music APIs or playlists are changed.

Use the explorer's NFC, trimmed, case-folded identity, retaining accents and
punctuation. Match artist names for follows, and artist plus title for albums
and tracks. Deduplicate identical Spotify identities. Return four evidence
categories: one exact name candidate, no exact name match, multiple candidates,
or collection unavailable. An exact name is evidence rather than verified
cross-service identity; unmatched names remain unresolved. Last.fm album IDs
are never interpreted as Spotify IDs. Display at most five candidates while
retaining their complete distinct count.

## Options considered

| Option | Benefit | Cost or limitation |
| --- | --- | --- |
| Strict normalized name evidence | Explainable, fast, available from existing publications | Spelling and edition differences remain unresolved; names can collide |
| Fuzzy matching and edition stripping | More candidate suggestions | Could incorrectly assert membership; needs separate evidence and review |
| Live catalog lookups | Potential identifier corroboration | Adds API availability, credentials, rate limits and enrichment storage |
| Read hydrated working files | Minimal new acquisition code | Does not establish publication identity or a coherent revision |

## Consequences

The history explorer remains useful when one or all collections are unavailable.
Publication dates, collection meanings, evidence limits and both version tokens
remain explicit in the UI and CSV. Coverage counts reconcile before evidence
and search filters. Charts drill into evidence rows; rows open original history
and optional Spotify candidate links. Pagination and exports are bounded.

The new `LibraryDataService.export_at_snapshot` operation is read-only and reuses
the existing restore/checksum boundary. Its original `export_snapshot` contract
and retry behavior remain unchanged. The exact concrete collection refresh
method has a documented `asyncio.to_thread` reason in the existing callback
ledger. No forwarding application stages or generic execution callbacks are
introduced.

Metadata enrichment, fuzzy resolution, playlist creation and routine launches
remain separately scoped follow-ups.
