# Listening Explorer: Album Quilt review

Date: 22 November 2026. Branch: `codex/listening-album-quilt`.
Status: implementation candidate; deployment and merge require owner approval.

Artist Atlas PR #94 was approved, deployed and verified before merge
`86d364ffe548d0b7f0e83c9d044fc77406f32f03`. The deployed private Space revision
is `72745965aeab3ff821001dd1fdd1b0d14d5b8695`. Its final CI passed 12,829 tests;
31 health checks over fifteen minutes returned no failures. The approved live
MusicBrainz test retained eight artist observations from fifteen total attempts,
with all 339,401 plays reconciled. That artist test does not authorize sending
private album titles to new providers. No private album lookup test is performed
as part of preparing this candidate.

## Delivered behavior

Album Quilt ranks the selected recorded albums in 3×3, 4×4, 5×5 or 7×7 layouts.
Search album/artist names, toggle captions, reload cached artwork and open a tile's
original recorded history. URL options restore on reload. Each unavailable cover
keeps a styled labelled fallback; artwork never changes album ordering.

Coverage separates all selected plays, named albums, missing-album plays, displayed
plays and named-album plays outside the quilt. The evidence table reconciles every
displayed album and play across available covers, no approved front, unmatched
names, ambiguous names, incomplete searches and never-looked-up albums.

Opening/filtering the page reads only cached metadata and images. Explicit batches
of five or ten visible missing/stale albums send titles and artist names to
MusicBrainz, then request representative artwork from Cover Art Archive/Internet
Archive. Counts, scrobbles and account identifiers are not sent. Thirty-day reuse,
force refresh, progress and cancellation are visible. Country and cover lookups
share MusicBrainz's sequential 1.1-second request-start limit.

One complete exact title/complete-credit candidate supports a representative
release-group cover. A name candidate does not verify identity or the edition
heard. Edition labels, accents, punctuation and join phrases stay significant.
Original candidates, representative release/image, retrieval dates and both
version tokens remain inspectable. See [ADR 007](../adr/007-representative-album-covers.md).

CSV exports the exact visible ranked quilt with complete applied context. PNG
includes dates, filters, versions, source credit and the number of embedded covers.
Available authenticated local images are embedded; missing/unavailable images
become labelled tiles. A metadata or image failure preserves historical totals,
the table and available exports. Locking clears artwork and revokes object URLs.

## Operations and contracts

`LISTENING_COVER_CACHE_DIR` selects a separate app-owned directory per process.
The default is `spotify-listening-covers` under the system temporary directory.
Only `album-covers-v1.sqlite` is retained, holding at most 256 observations and
bounded JPEGs. Oldest observations are evicted. Full auto-vacuum bounds reclaimed
space; a page ceiling further bounds the database. Two complete in-memory `c1-`
generations retain their own image bytes. Restarts reuse valid files; rebuilds or
temporary-directory cleanup can reset this derived cache. Stop the process before
deleting it. Only explicit new lookups refill it. Country/tag caches and canonical
history/shared state need no migration and are unchanged.

Five additive protected routes preserve existing operations and schemas:

| Method and route | Purpose |
| --- | --- |
| `GET /lastfm/analytics/quilt/status` | Independent cover token and batch progress. |
| `GET /lastfm/analytics/quilt` | Bounded ranked albums, current evidence and complete scope. |
| `GET /lastfm/analytics/quilt/images/{album_key}` | Validated local bytes pinned to the cover generation. |
| `POST /lastfm/analytics/quilt/refresh` | Explicit batch from the displayed pinned-history quilt. |
| `POST /lastfm/analytics/quilt/cancel` | Cancel while draining active work. |

Data/byte responses are private/no-store. The existing application gate protects
all five routes; no artwork image route is publicly allow-listed. An expired
cover generation returns 409 with `X-Listening-Conflict: covers`. History and other
metadata versions are independent. Mutable explorer URLs advance together to
revision 6; ECharts stays pinned. The new locked Pillow dependency validates small
JPEGs. Existing interfaces, canonical storage and routine behavior remain frozen.

## Verification and review

Focused hand-counted tests cover selection scope, ties, missing albums, same titles
across artists, edition labels, Unicode, all evidence outcomes, freshness and empty
quilts. Source/cache tests cover complete artist credits, query escaping, ambiguous
and incomplete searches, malformed/oversized responses, validated redirects,
JPEG dimensions/decoding, atomic metadata/image persistence, eviction/restart,
corruption, shared cross-feature spacing and drained cancellation. HTTP tests cover
all five gates, independent versions and preserved history. Browser tests cover
controls, rank-to-history navigation, explicit fetch, reloads, mobile, hostile text,
unavailable metadata/images and real CSV/PNG downloads. The PR records final full
CI, independent coverage, package verification and local preview evidence.

Public integration probes used only MusicBrainz documentation examples: the
Fred Giannelli / Main Tenance exact search returned one candidate with no current
cover, and the documented archive thumbnail redirected successfully and validated
as a 10,703-byte JPEG. No private titles or listening history were submitted.

Local focused verification passes 115 tests: the new domain, provider, image
validation, cache and codec modules have complete statement/branch coverage.
The combined focused report is 99.87%, with all statements covered. Twenty browser
scenarios plus seven JavaScript checks pass, including preceding explorer views.
Package typing checks 794 files; strict business/test verification checks 527 files.
All eleven public interface comparisons preserve existing operations and schemas,
with five additive routes. The wheel contains 811 Python/frontend files; its isolated checks cover both
entry points, all 45 commands and the protected image route. Final CI and
installed-wheel review results follow in the PR.


The installed-wheel real-history preview reconciles 339,401 plays, 31,510 named
album identities and 1,943 plays without album names. Quilt sizes 9/16/25/49
match the core album ranking exactly and represent 15,025 / 24,141 / 33,776 /
51,593 plays respectively. All visible outcome totals reconcile. Five data/byte
gates reject missing credentials; no provider batch is started by any read.
Shared state is unchanged, and all 25 preceding tag observations and eight country
observations remain available in their independent caches.

Real-history review: **http://127.0.0.1:8765/lastfm?tab=quilt&preset=all**.
Labelled synthetic-art review:
**http://127.0.0.1:8766/lastfm?tab=quilt&preset=all**.
Password for both: **`preview`**. Both launchers explicitly set and print it.
The installed candidate wheel keeps hydration and caches outside source mirrors.
The sample labels its synthetic albums, covers, counts and simulated fetches.
No private album names have been sent to the public cover services by this test.

The local full regression run passed 12,936 tests and all independent coverage
floors. Subsequent malformed-provider cases pass in the 115 focused tests; final
CI reruns the complete final source on the review commit. Architecture/bootstrap
and lifespan checks pass 162 tests. The final 811-file wheel, both entry points
and all 45 commands pass in an isolated installation. All twenty browser scenarios
and seven JavaScript checks pass, including real PNG/CSV downloads and readable
placeholder exports. Review captures show both installed-wheel previews.


A positive live check uses the documented release-group MBID
`48140466-cff6-3222-bd55-63c27e43190d`, independently of private history. Its
published title/credit passes the normal exact-name search, archive-index lookup,
validated redirects and JPEG decoder, producing a ready 10,703-byte cover. The
archive currently returns numeric image IDs; both bounded nonnegative integers
and documented digit strings normalize to the same stored string identity.
Booleans, fractions, negative and oversized IDs are rejected. The first attempts
encountered provider-unavailable responses before a successful complete read.
No private names, counts or scrobbles were submitted.
