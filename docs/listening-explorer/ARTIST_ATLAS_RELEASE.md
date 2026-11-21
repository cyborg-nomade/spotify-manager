# Listening Explorer: Artist Atlas review

Date: 21 November 2026. Branch: `codex/listening-artist-atlas`.
Status: prepared for owner review; deployment and merge require approval.

Tag Atlas was approved, deployed, verified and merged in PR #93 before this
branch started from clean updated master. This increment implements the next
artist-map view using [ADR 006](../adr/006-artist-country-associations.md).

Local review: **http://127.0.0.1:8765/lastfm?tab=origins&preset=all**.
Local password: **`preview`**. Startup prints both values. The preview runs a
candidate wheel in an isolated temporary installation, keeping normal hydration
and derived metadata outside source-checkout mirrors.

## Delivered behavior

- Artist map shows current MusicBrainz country associations applied to selected
  listening. Switch map values between actual selected plays and artist counts.
  Pan/zoom, select a country, inspect candidates and open original artist history.
- One exact-name candidate with one reported country supports country totals.
  Name evidence never verifies cross-service identity. Multiple candidates,
  multiple countries, missing countries, incomplete searches, unmatched names
  and artists never looked up have separate counts. All plays reconcile.
- Main associated area and reported birth/formation area remain separate in the
  evidence. Country associations do not establish historical origin, nationality
  or the listener's location. Retrieval dates describe current metadata.
- Opening/filtering the view reads cached data only. Explicit batches of 10 or
  25 highest-play missing/stale artists send artist names to MusicBrainz; no
  scrobbles, play counts or account history are sent. Thirty-day freshness,
  optional force refresh, progress and cancellation are visible.
- Country/evidence/search filters, page navigation and map-value choices restore
  from the URL. CSV exports either all country counts with an explicit residual,
  or the current artist page with applied options and source provenance. PNG
  includes historical and metadata versions, retrieval dates and source credit.
- Bundled public-domain Natural Earth outlines load locally, without remote tiles
  or trackers. Small/historical countries remain in tables when no outline exists.
  An outline failure preserves country tables/CSV; metadata service failures
  preserve historical totals. Expired country versions recover independently.

## Operations and contracts

MusicBrainz public searches require no new account or API key. The fixed source
sets a descriptive User-Agent, spaces starts by at least 1.1 seconds even across
batches, reads at most one MiB with a fifteen-second socket timeout, and does not
retry automatically. A provider outage stops the batch without deleting data.
Completed cache commits survive cancellation. The derived cache retains at most
20,000 artists, evicting oldest observations, plus two complete in-memory versions.

`LISTENING_ORIGIN_CACHE_DIR` selects an app-owned directory per process. Its
default is `spotify-listening-origins` under the system temporary directory;
the only file is `artist-origins-v1.sqlite`. Process restarts reuse files while
they remain; container rebuilds or temporary-directory cleanup can reset them.
Stop the process before deleting this derived cache. Only explicit new batches
refill it. Tags use their independent cache. Canonical data and shared state
require no migration and are unchanged by this feature.

Four additive protected routes preserve every prior operation and schema:

| Method and route | Purpose |
| --- | --- |
| `GET /lastfm/analytics/origins/status` | Independent metadata token and batch progress. |
| `GET /lastfm/analytics/origins` | Cached country totals and bounded artist evidence. |
| `POST /lastfm/analytics/origins/refresh` | Explicit bounded public searches and derived cache writes. |
| `POST /lastfm/analytics/origins/cancel` | Cancel while draining active work. |

All data responses are private/no-store and retain the application password gate.
`metadata_snapshot` uses the independent `o1-` token. History `snapshot` remains
mandatory. Mutable explorer modules/styles advance together to revision 5;
ECharts remains pinned. Static assets add only the helper, outlines and notice.
Source/dependency inventories remain frozen; only intentional additive HTTP
contracts extend their baselines.

## Verification

Hand-calculated fixtures cover all evidence outcomes, complete count/share
reconciliation, Unicode identity, country filters that retain ambiguous evidence,
pagination, freshness and empty selections. Concrete boundary tests cover query
escaping, malformed/oversized responses, source failure, exact-name candidate
bounds, cross-batch request spacing, cancellation draining, cache persistence,
eviction/corruption and independently expired metadata. Synthetic browser checks
exercise map selection, both value modes, CSV, history details, explicit fetch,
URL restoration, escaped names, mobile layout and unavailable outlines/metadata.
The review PR records final test, package and real-history preview results.


Local verification: 58 focused feature tests pass, with full statement and
branch coverage for the new domain, provider and cache modules, and 99.83%
combined coverage across those modules and the enrichment stage. All seventeen
browser scenarios plus seven JavaScript checks pass, including the existing
explorer regressions. Package and strict business/test typing pass. The 797-file
wheel passes both entry points and all 45 command checks. The eleven interface
comparisons preserve all prior operations/schemas, with four additive routes.

A public provider probe uses MusicBrainz's documented example name Fred,
independently of private history. MusicBrainz returned its busy (503) response
during preparation; no history-derived artist names were sent in that probe.
Controlled tests verify the safe failure path. The PR records subsequent
provider availability and any separately approved real-history lookup test.

The isolated real-history preview reconciles all 339,356 scrobbles and 15,696
artist identities across complete evidence outcomes. Its initially empty country
cache remains explicit, with no provider reads during page rendering. All four
new route gates and private response headers pass. The preceding 25 local tag
observations remain available in their independent cache. Mobile map proportions
are preserved; browser checks exercise an actual country-shape selection.
