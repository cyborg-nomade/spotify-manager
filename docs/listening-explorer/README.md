# Listening Explorer

The companion page at **`/lastfm`** explores the complete published Last.fm
history. Open **Explore ↗** beside Sync and Download in the cockpit's Last.fm
row, or navigate directly to the page. It uses the existing app password.

## Delivered views

- **Overview:** exact scrobble/artist/track/album counts, calendar-day versus
  active-day averages, a navigable yearly listening calendar, weekday/hour rhythm,
  searchable artist/album/track rankings, and the underlying recorded plays.
- **Taste over time:** fixed top-eight-plus-Other artist trajectories, count/share
  display, weekly/monthly buckets, recorded artist/track breadth, concentration,
  and comparison with the immediately preceding equal-length calendar period.
- **Discoveries:** first-observed artist cohorts and 7/30/90-day return rates,
  using separate complete-window denominators and explicit pending follow-up.
- **Time capsule:** On This Day revisits earlier anniversaries; Musical Eras
  compares the complete artist mix between calendar periods.
- **Rediscover:** historically substantial artists/albums/tracks with adjustable
  minimum-play and inactivity thresholds, as of the selected analysis end date.

Select a ranking/table entry or an artist chart series to open entity history.
The detail panel separates lifetime facts through the analysis cutoff from
counts inside the visible period. Original source names remain visible in the
paginated scrobbles, including spellings grouped under one analytics identity.

Calendar selection opens that day's recorded plays. Rhythm selection adds
visible weekday/hour filter chips. Discovery and rediscovery use full calendar
days; switching to those tabs or Time capsule clears rhythm filters. Their API routes reject
rhythm filters rather than changing first-observed semantics silently.

## Filters and interpretation

Date presets end at the latest **stored scrobble**, not the current clock time.
The end date, source publication time, and stale-history notice remain visible.
Choose custom dates to include today or any other interval. Filters and selected
entities are restored from the URL. Credentials never appear in the URL.

Europe/Berlin is the default aggregation zone. UTC and other valid IANA zones
are supported. Calendar boundaries are converted explicitly with `ZoneInfo`;
the host's local timezone is not used. Rhythm averages divide by the actual
covered duration of each weekday/hour, including fractional source boundaries
and the repeated or missing hours at DST transitions.

All counts are recorded scrobbles, including repeated source rows. A zero means
zero recorded observations, not proof that no listening happened or that the
scrobbler worked. Calendar cells distinguish source boundaries and dates outside
the observed range. Blank albums remain included in scrobble/artist/track totals,
but are excluded from unique-album counts and reported separately.

Artist identities use NFC, trimmed whitespace, and case folding, preserving
accents and punctuation. Track and album identities include artist context.
Existing routine matching rules are unchanged. Source album IDs are preserved
as opaque identifiers, never assumed to be Spotify IDs.

"First observed" means first recorded in the available source history. Returns
require a play on a different calendar day within the chosen inclusive window.
The latest source day is conservatively partial; artists without a complete
follow-up window are pending, not failed discoveries. Forgotten Favorites ignores
the visible start date and excludes scrobbles after the selected analysis end.

## Time capsule

**On This Day** uses the selected **Through** date as its month/day anchor. It
shows earlier years across the available source history, independently of
**From**, retaining the optional artist filter and selected timezone. The anchor
year and later years are excluded. February 29 appears only in leap years.
Covered days with zero recorded plays remain distinct from dates outside source
coverage; first/last source days are partial. Up to five leading artists appear
per day. Select a date to open its original recorded plays.

**Musical Eras** compares all recorded artist identities in each selected period,
including artists outside the overview's top eight. Artist counts become shares
within each period. Similarity is weighted Jaccard:

```text
sum(min(left artist share, right artist share))
------------------------------------------------
sum(max(left artist share, right artist share))
```

Identical mixes score 100% even if listening volumes differ; disjoint mixes score
0%. A comparison involving an empty period is undefined, including its diagonal.
Empty cells stay blank and tables/CSV say **Not comparable**. Self-comparisons
use a subdued gray diagonal, separate from the similarity palette. Values are rounded
to six decimals. The chart describes recorded artist mix rather than real-life
events. Selection and source boundaries mark partial periods explicitly.

Selections of up to 240 calendar months use months. Longer selections use
calendar years, with the grain explicitly reported in the response and UI. This
bounds the matrix without dropping older history. The existing 100-year query
bound remains in force. The heatmap uses six fixed, high-contrast bands: <2%, 2–5%, 5–10%, 10–20%,
20–35%, and ≥35%. Exact values remain in tooltips and tables. The **Highlight
similarity at least** slider dims lower scores without removing comparisons.
Its setting applies on release and is restored from `era_min` (whole percentages).

**Group similar periods** reorders both axes, the reference selector and the table
using deterministic average-linkage clustering over the existing similarity
matrix. Every original period has equal weight in average linkage; no artist or
play counts are recomputed. Ties use earliest source-period indices. Each merge
keeps its earliest child group first. Empty periods are excluded from clustering
and appended in calendar order. Turning grouping off restores chronological order.
Grouping is restored from `era_order=grouped`. The derived ordering is cached
for the current result, and rendering maps every cell back to its original
period indices for tooltips and selection.

The heatmap has zoom controls for longer ranges. Use its
cells or the **Compare with period** selector to inspect a reference column in
the accessible table. The reference is restored from `era_ref` in the URL.
Select a period row to open its recorded plays in Overview.

## Tables and exports

Equivalent tables accompany charts. Keyboard users can select the same entities,
dates, and rhythm cells through buttons in those tables. Reduced-motion settings
disable chart animation. Mobile uses a single column and a native dialog for
details.

PNG exports include chart labels, dates, timezone, and source identity. CSV
exports include the effective shared filters and source token; rankings and
records export the displayed page. Musical Eras exports the complete matrix
with counts, effective period bounds and coverage. Matrix rows and columns follow
the displayed ordering, while scores remain unchanged. Export metadata records
the ordering, fixed bands and highlight threshold; dimmed values remain included. On This Day exports earlier
anniversaries with the full-archive start, anchor date and source coverage. CSV text cells are protected against
spreadsheet-formula interpretation. The cockpit's existing Download control
still exports the original complete published JSON unchanged.

## Storage, ownership, and execution path

```text
HTTP route beside endpoint
  → named application use case
  → named read resource + direct domain rules
  → typed HTTP presenter
```

The page reads the **published** scrobble artifact through `LibraryDataService`
and `ScrobbleHistoryFiles`. It does not read a mutable sync-in-progress working
file or request live Spotify/Last.fm data. Source acquisition is revision-pinned
and verifies the existing checksum and byte-size contract.

The runtime lazily builds a standard-library SQLite index in an independently
owned temporary directory. `LISTENING_CACHE_DIR`, when set, selects an existing
parent directory for that temporary cache. The default is the operating system's
temporary directory. Each web process has an isolated cache, so no cross-process
writer lock is needed. The application lifespan owns the single refresh task and
drains it through cancellation before removing its files.

The first authenticated status request starts source acquisition and indexing.
Further manifest checks are limited to once per 60 seconds unless the user
requests **Check publication again**. A full source checksum change creates a
new generation, even when the row count is unchanged. A failure retains the last
complete index and reports stale/error status. A missing publication links back
to the existing cockpit sync controls.

Every data request pins the source token obtained from status. All widgets use
that token together; an expired token returns 409 and the browser reloads the
whole selection. Active readers keep their generation alive during replacement.
The latest two generations are retained, plus any older active readers.

Each generation materializes at most four IANA calendar tables. HTTP results use
bounded process-local memoization keyed by immutable reader identity, typed
query, and options. SQLite queries use fixed identifiers and separately bound
values. Read connections are read-only. The derived cache never publishes data,
changes routine state, or mutates a playlist.

Cold starts and process replacements rebuild this cache. Canonical publications
and their durable backups are unaffected by cache deletion or rollback.

## HTTP interface

All data routes require the existing `X-App-Password` header in the deployed
web wrapper. The data-free shell and exact versioned JS/CSS/chart assets are
open so the login interface can load. The whole `/lastfm/` prefix is never
allowlisted. The pure API retains its original trusted-loopback boundary.

| GET endpoint under `/lastfm/analytics` | Result |
| --- | --- |
| `/status` | Ready/building/stale/missing/error state and source/build metadata; optional `refresh=true`. |
| `/overview` | Exact selected counts and separate averages. |
| `/activity` | Local calendar coverage and all weekday/hour cells. |
| `/rankings` | Searchable/paginated artist, album, or track counts. |
| `/evolution` | Weekly/monthly artist series and aligned breadth. |
| `/entities/{kind}/{key}` | Pre-cutoff lifetime facts and filtered detail. |
| `/scrobbles` | Original recorded names with stable timestamp/source-order paging. |
| `/discovery` | First-observed cohorts and eligible/returned counts. |
| `/rediscovery` | Historical-play/gap thresholds as of the analysis cutoff. |
| `/comparison` | Current/previous equal-length artist counts and shares. |
| `/eras` | All-artist weighted Jaccard matrix, period counts and coverage. |
| `/on-this-day` | Earlier anniversaries of `to`, full history independent of `from`. |

Data routes require `from`, `to`, and `snapshot`; `tz` defaults to Europe/Berlin.
Optional shared filters are `artist`, Monday-based `weekday`, and `hour`.
Rankings additionally accept `kind`, `q`, `page`, `limit`, and `order`. Scrobble
pages accept `page`, `limit`, and an optional `kind`/`key` pair. Rankings cap at
100 rows, records at 200, evolution at eight artists plus Other, and rediscovery
at 100 results. Date selections are bounded to 100 years within 1900–2099.

Successful protected responses use `Cache-Control: private, no-store`.
The shell and mutable application assets send `Cache-Control: no-cache`. The
entry script, stylesheet and every local module import carry the same explicit
asset revision (`v=3`), bypassing older cached URLs. The pinned ECharts 6.0.0
distribution retains an immutable cache policy. A browser upgrade test seeds the
complete older module/style graph with a long-lived cache, then verifies normal
navigation loads the current working controls.

Music names are rendered as text, and ECharts uses rich-text canvas tooltips
rather than parsing names as HTML.

## Development and checks

Run the ordinary web entry point from the feature branch:

```console
printf 'Local preview password: preview\n'
APP_PASSWORD=preview uv run --env-file .env uvicorn spotify_manager.web:app --host 127.0.0.1 --port 8765
```

Local review previews use password **`preview`**. Set it explicitly for the
preview process and announce the URL and password at each start and handoff.

The chart distribution is Apache ECharts 6.0.0, served locally with its license
and notice files. Its npm archive SHA-512 was verified before extraction. No
production JavaScript package installation or bundling step is required.

The browser-test dependency is isolated in `tests/browser`, pinned with its npm
lockfile. Tests serve the actual page/router/assets over synthetic local
publications and never use operator history or credentials:

```console
npm ci --prefix tests/browser --ignore-scripts --no-audit --no-fund
tests/browser/node_modules/.bin/playwright install chromium
npm --prefix tests/browser test
```

To use an existing Chrome installation, set `LISTENING_CHROME_PATH` to its binary.
CI uses Ubuntu 24.04 with its pinned Playwright Chromium and retains
screenshots/failure traces. The runner version matches that browser release's
supported system dependencies.
The browser test command also runs seven pure JavaScript checks for band
boundaries, size-weighted average-linkage updates, deterministic and empty-period ordering,
coordinate mapping, threshold semantics and the 240-period bound.
The existing Python, architecture, frozen-interface, and independent coverage
gates remain required. The wheel smoke check now verifies all explorer assets.

Read-only benchmarks can use the published artifact, an explicit local JSON, or
a synthetic source. They create and remove their own snapshot/index files:

```console
uv run python docs/listening-explorer/benchmark.py --published --output build/reports/listening-published.json
uv run python docs/listening-explorer/benchmark.py --synthetic 1000000 --output build/reports/listening-million.json
```

The tool reports cold build/query costs, warm p95 including serialization,
response size, derived disk usage, and peak process memory. It does not print
music names or credentials. Warm local timings do not establish deployment
latency; verify the same paths after the approved Space deployment.

## Follow-up scope

The approved core and discovery/rediscovery views are deployed. Playlists and
session inference remain optional follow-ups. Album Quilt is prepared for review
with independent representative-artwork caching. Library Bridge adds published
Spotify-library comparisons;
Tag Atlas adds current community-tag enrichment; Artist Atlas adds reported
country associations. The
Time Capsule release adds Musical Eras and On This Day. The current export
cannot establish listening minutes,
skips, completion rates, mood, or historical location.

See [the approved plan](IMPLEMENTATION_PLAN.md) and
[first release verification](RELEASE_VERIFICATION.md) and
[Time Capsule release verification](TIME_CAPSULE_RELEASE.md) for scope, evidence, and release
status. Both releases were approved by the owner and verified on the deployed
Space before merge.


## Library Bridge release

The [approved release](LIBRARY_BRIDGE_RELEASE.md) compares the selected
listening history with published saved albums, liked tracks and followed
artists. Collection publication dates are independent of listening dates.
Coverage distinguishes exact normalized name candidates, unresolved names,
multiple Spotify candidates and unavailable sources. Unmatched names never
establish absence, and name matches never establish verified cross-service
identity. Edition labels, accents and punctuation remain significant.

The Library Bridge tab includes a coverage chart/table, evidence and search
filters, selected-play thresholds, pagination, history detail navigation,
Spotify candidate links, URL restoration, PNG and current-page CSV. CSV includes
both publication identities, collection date, evidence settings and page scope.
The two new protected read-only routes are `/lastfm/analytics/library/status`
and `/lastfm/analytics/library`; comparison requests pin `library_snapshot`
in addition to the existing history `snapshot`. Collection failures preserve
historical views. The Check publications control retries independently.

See [ADR 004](../adr/004-published-library-evidence.md) for matching limits and
immutable multi-artifact acquisition. Further enrichment and fuzzy resolution,
playlists and routine launch controls remain separate follow-ups.


## Tag Atlas release

**Tags & genres** applies current cached Last.fm community labels to monthly
listening. Choose a leading label or equal allocation among up to three labels,
and allocated plays or share. Eight leading tags, Other and Unknown account for
all selected plays. These labels describe current community metadata, rather
than verified genres at the time of listening.

Coverage distinguishes artists with tags, verified empty tags, unresolved names,
and artists never looked up. Retrieval dates and source links accompany the
evidence. Opening the page only reads cached metadata. Expand coverage with an
explicit batch of 10, 25 or 50 artists, or cancel while retaining completed work.
Recent observations are skipped for thirty days unless force refresh is chosen.

Tag/search filters, pagination, history details, URL restoration, CSV and PNG are
available. History remains usable when enrichment is unavailable. See the
[release record](TAG_ATLAS_RELEASE.md) for configuration, cache lifetime, endpoint
contracts and validation, and [ADR 005](../adr/005-current-community-tag-evidence.md)
for evidence limits. The release was approved, deployed and verified before merge.


## Artist Atlas release

**Artist map** shows current MusicBrainz country associations for artists in the
selected history. A complete search with one exact-name candidate and one country
supports country totals; ambiguous names, multiple countries and missing or
incomplete evidence remain separate. Country associations do not prove historical
origin, nationality, or where you listened.

Switch selected plays/artist counts, pan/zoom, select a country, inspect original
provider candidates and open recorded history. Complete country/coverage tables,
CSV and PNG retain source dates and versions. No metadata searches happen on page
load. Explicit batches of 10 or 25 artists expand coverage through MusicBrainz.
The locally bundled map needs no remote tiles and has a table fallback.

See [the release record](ARTIST_ATLAS_RELEASE.md) for configuration and contracts
and [ADR 006](../adr/006-artist-country-associations.md) for evidence limits.
The owner approved this release and its bounded MusicBrainz test before deployment.


## Album Quilt review

**Album quilt** arranges the selected top albums into 3×3, 4×4, 5×5 or 7×7 tiles.
Search album/artist names, toggle captions and open original recorded history.
Missing art keeps its tile and rank. Complete scope counts distinguish selected,
displayed, outside-quilt and missing-album plays.

The page only reads cached art. Explicit five/ten-album batches send visible
titles and artist credits to MusicBrainz and fetch representative Cover Art
Archive/Internet Archive thumbnails. One exact title/complete-credit candidate
supports current representative artwork; it does not verify the edition heard.
Ambiguous/incomplete names stay unresolved. Current source links, retrieval dates,
coverage and independent versions accompany the quilt. PNG embeds available local
images and uses labelled placeholders for unavailable art; CSV exports every tile.

See [the review record](ALBUM_QUILT_RELEASE.md) and
[ADR 007](../adr/007-representative-album-covers.md) for evidence, cache lifetime,
protected routes and provider boundaries. This candidate awaits owner review.
