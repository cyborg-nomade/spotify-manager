# ADR 006: Map current country associations with explicit name evidence

**Status:** Accepted by the owner in PR #94 on 22 November 2026.
**Date:** 21 November 2026.

## Context

The approved explorer plan lists an artist-origin map after tag enrichment.
History names alone do not establish MusicBrainz identity. MusicBrainz's main
associated area is often a birth/formation country, but does not guarantee that
meaning. Its begin-area is separate and may lack a country. Neither identifies
the listener's location. Geography therefore needs source-aware, conservative
labels and explicit unknowns rather than inferred origins from names or tags.

## Decision

Label the view **Artist atlas**, describing reported country associations.
Read current MusicBrainz artist-search metadata only after an explicit protected
POST. Send the captured artist name and public query options, without account
identifiers, play counts, listening records or location. Use escaped
`artistaccent` phrases, then corroborate NFC, trimmed, case-folded names while
retaining accents and punctuation. Search scores and aliases never resolve
identity. Keep at most five distinct MBID candidates and their complete found
count. Any incomplete search remains incomplete, even if only one candidate was
returned. A unique name candidate remains evidence rather than verified identity.

Only a complete search with one exact-name candidate and one reported geographic
country contributes to country totals. Multiple names, multiple countries,
missing countries, unmatched names, incomplete searches and artists never looked
up remain separate evidence categories with complete play and artist totals.
Do not split ambiguous plays between countries. Worldwide/Europe codes are not
mapped as countries. A country evidence filter can still inspect ambiguous
candidates reporting that country. Display associated area, begin-area, source
links and retrieval dates separately. Country shares use all selected plays,
including unresolved coverage, as their denominator.

GETs only read the independent derived cache. Explicit batches select up to
25 highest-play missing or thirty-day-old artists from one pinned history
selection. One owned stage runs at a time. The public source resource also
serializes requests and spaces starts by at least 1.1 seconds across batches,
with a descriptive User-Agent, bounded one-MiB responses, fifteen-second socket
timeouts and no hidden retries. Provider errors stop the batch while retaining
complete cached entries. Cancellation drains active blocking reads or commits.
Bootstrap owns resource construction; application code directly calls named
resources and fixed domain rules. Shutdown drains origins before tags,
collections and history, after routine jobs have closed.

Use a separate fixed derived SQLite file outside canonical data and shared state,
with a twenty-thousand-observation limit and oldest-first eviction. Retain two
immutable `o1-` metadata generations, independent of history and community tags.
Expired country metadata returns 409 with `X-Listening-Conflict: origins`;
recover it independently. Separate cache directories are required per process.
A process restart reuses available cache files; a rebuild may remove them.

Bundle pinned Natural Earth 1:110m outlines locally. Preserve geometries and only
map identifiers/labels; retain distinct identifiers for outlines without ISO
codes. The original source, revision and both checksums accompany the asset.
No map tiles, third-party scripts, geocoding or image requests occur when the
page renders. Small or historical countries may appear only in complete tables.
If outlines cannot load, keep the tables, coverage, exports and history usable.

## Alternatives and consequences

Inferring country from tags would conflate community labels with geography.
Automatically choosing the first search hit would conceal collisions. Resolving
birth/formation-country ancestry would require additional area-relation evidence
and more requests; that can be reviewed separately. The current association
model provides a useful map with explicit limits and a direct route to evidence.
Manual identity resolution, fuzzy matching and historical nationality remain
outside this release. Country boundaries are a coarse visual aid; complete
reported codes remain exportable even without matching outlines.

Sources: [MusicBrainz artist properties](https://musicbrainz.org/doc/Artist),
[search contract](https://musicbrainz.org/doc/MusicBrainz_API/Search),
[identification and rate limits](https://musicbrainz.org/doc/MusicBrainz_API),
[Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/).
