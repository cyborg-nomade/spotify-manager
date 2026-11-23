# ADR 007: Cache representative album covers with explicit name evidence

**Status:** Accepted by the owner in Album Quilt PR #95 on 22 November 2026.
**Date:** 22 November 2026.

## Context

Artist Atlas was approved, deployed, verified and merged in PR #94 before this
increment started from clean master. The approved next view is an album quilt.
The canonical scrobble export has album names, artists and opaque album IDs, but
no reliable cover images or verified MusicBrainz release identities. Missing
artwork must not remove albums from the ranking or prevent an image export.

## Decision

The [provider reliability update](../listening-explorer/PROVIDER_RELIABILITY.md)
checks each batch with Last.fm first. The archive path below remains the
fallback for albums without usable exact-match Last.fm thumbnails.

Rank exact recorded album/artist identities by selected plays. Offer 3×3, 4×4,
5×5 and 7×7 quilts, original-history navigation, title/artist search, caption
visibility and URL restoration. Keep blank-album plays separate. Reconcile every
visible tile and its plays across available, absent, unmatched, ambiguous,
incomplete and never-looked-up cover evidence. Report named-album plays outside
the quilt separately. Artwork availability never changes rank or listening counts.

GETs read only an independent derived cache. An explicit authenticated POST
captures up to ten highest-ranked missing/thirty-day-old albums from the displayed
quilt. It sends album titles and artist credits to a fixed MusicBrainz
release-group search, without account identifiers, counts or scrobbles. Escape
Lucene syntax, then corroborate NFC, trimmed, case-folded titles and complete
credited artist strings, including join phrases. Preserve accents, punctuation
and edition suffixes. A release group represents an album concept, not a specific
edition heard. Scores, fuzzy matching, partial artist credits and opaque source
album IDs never resolve identity.

Only a complete search with one distinct exact-name group candidate may fetch
artwork. Retain at most five candidates and the full found count. Unmatched,
ambiguous and incomplete searches remain separate. For a unique group, read the
Cover Art Archive's representative-release index and choose its first approved
main-front entry in archive order. Retain the actual release MBID, image ID,
retrieval date, dimensions and image SHA-256. A documented 404 or no approved
front becomes explicit unavailable artwork. [Shared retry rules](../listening-explorer/PROVIDER_RELIABILITY.md)
cover temporary failures. An exhausted retry, malformed response or invalid image
stops the batch and retains prior complete observations. Each attempt uses the
same exact title and credit.

Use the archive's fixed 250px JPEG endpoint. Follow at most four redirects through
validated HTTPS MusicBrainz, Cover Art Archive or Internet Archive hosts, upgrading
documented HTTP redirects. No arbitrary URL proxy, credentials or nonstandard
ports are accepted. Bound JSON to one MiB, image bytes to 128 KiB, socket operations
to fifteen seconds, check a thirty-second read budget between chunks/redirects,
and decoded dimensions to 1000×1000. Pillow validates JPEG
encoding before publication; it does not modify provider artwork. The new locked
Pillow dependency avoids maintaining a bespoke image parser.

Bootstrap owns one MusicBrainz request gate shared by the country and cover
resources. Serialize starts at least 1.1 seconds apart across views and batches.
Hold the gate and bounded blocking capacity until active reads drain, including
cancellation. Start the next spacing interval after that drain, so waiting for
worker capacity cannot spend the interval before an actual request begins. A named application stage directly calls its source and cache
resources. Sync FastAPI dependencies capture selected album counts off the event
loop; async endpoints only start/cancel owned background work. Job shutdown still
precedes enrichment, collection and history cleanup.

A separate fixed SQLite file stores each observation and its optional JPEG in
one transaction outside canonical data and shared state. Keep at most 256 albums,
evict oldest retrievals, use full auto-vacuum and an 80-MiB page ceiling. Retain
two immutable `c1-` generations, including the bytes belonging to their metadata.
A pinned reader retains its bytes across later eviction. Each process owns its
own directory. Process restart reuses valid files; rebuild/temporary cleanup may
reset the cache. Old country and tag cache formats remain unchanged.

Serve images only through a protected local route, requiring an album key and
cover generation. Return JPEG with private/no-store and no-sniff headers. Render
with authenticated fetches and local object URLs; browser image tags never point
to public providers. Abort obsolete reads and revoke URLs on selection changes
or lock. Expired metadata returns 409 with `X-Listening-Conflict: covers` and
recovers independently of history. Missing/expired image reads keep placeholders
and offer a cached-artwork reload. CSV and PNG include versions, filters, source
credit, retrieval dates and evidence limits. PNG embeds available local images;
unavailable art always becomes a labelled tile.

## Alternatives and consequences

Automatic remote image URLs would expose viewing activity, make exports depend
on third-party embedding policy and hide network calls during rendering.
Spotify mirror comparisons provide name evidence but no canonical cover images.
Looking up arbitrary album IDs or removing edition suffixes would overstate
identity. Manual identity/edition resolution remains separately scoped.

Conservative names can leave substantial missing-art coverage. Representative
artwork may differ from the edition actually heard. The visible evidence table,
source links and exact unchanged listening ranks make these limits inspectable.
The bounded cache can evict covers from older selections, requiring an explicit
new lookup when revisiting them. Cache failures preserve the historical dashboard.

Sources: [MusicBrainz release groups](https://musicbrainz.org/doc/Release_Group),
[search fields](https://musicbrainz.org/doc/MusicBrainz_API/Search#Release_Group),
[identification/rate limits](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting),
[Cover Art Archive API](https://musicbrainz.org/doc/Cover_Art_Archive/API),
[Pillow image validation](https://pillow.readthedocs.io/en/stable/reference/Image.html).
