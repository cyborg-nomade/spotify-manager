# Listening Explorer release candidate

Date: 16 November 2026. Branch: `codex/lastfm-listening-explorer`.

The owner approved the plan and authorized completing core and
discovery/rediscovery views together before requesting revision. This candidate
delivers those views in one feature branch. Optional enrichment and Spotify
actions remain follow-up scope.

Local review: **http://127.0.0.1:8765/lastfm**. The normal web app is running on
loopback, with the companion page linked from the cockpit's Last.fm row.

## Delivered scope

- Overview counts and separate calendar-day versus active-day averages.
- Yearly calendar and weekday/hour rhythm with explicit timezone/DST behavior.
- Searchable, paginated artist/album/track rankings and source records.
- Entity lifetime/period detail, related tracks, and paginated observations.
- Weekly/monthly fixed top-eight-plus-Other evolution with count/share display.
- Temporal breadth, concentration, and preceding-period comparisons.
- Discovery cohorts with complete-window 7/30/90-day return denominators.
- Forgotten Favorites with historical-play and inactivity thresholds.
- URL-restored filters/entities, table alternatives, keyboard/mobile use,
  reduced motion, and CSV/PNG exports.
- Published-only, checksum-verified acquisition and disposable SQLite generations;
  one pinned source version across each complete browser selection.
- Bounded timezone/result caches, stale-index recovery, active-reader retention,
  and cancellation-drained shutdown cleanup.
- Exact static-asset allowlist; deployed analytics retain the existing password
  gate. No live music API calls or playlist/state mutations are added.

The cockpit receives one navigation link and no source reorganization. All
pre-feature HTTP routes/model schemas were compared semantically to
`origin/master` and remain unchanged. Only additive explorer contracts were
recorded; frozen CLI, settings, state, and Spotify-call contracts remain intact.

## Published history and scale verification

The read-only benchmark acquired and verified the actual published artifact:

- 338,698 scrobbles; 38,880,491 uncompressed bytes.
- Calendar coverage: 27 November 2007 through 16 November 2026 in Europe/Berlin.
- Publication: 16 November 2026, 13:08:21 UTC.
- SHA-256: `c4b2bd097f45d2610e7f9992b350e788b74f9453cc56f173cdc9de84b2c854a5`.

This is newer than the working export inspected during planning. The explorer
uses the durable publication independently of that older copy.

Development-machine measurements:

| Measurement | Published history | Synthetic million rows |
| --- | ---: | ---: |
| SQLite build | 2.56 s | 6.15 s |
| Cold evolution query/serialization | 0.69 s | 1.86 s |
| Warm activity p95 with serialization, all time | 18.60 ms | 15.51 ms |
| Index plus one timezone | 98.0 MB | 217.9 MB |
| Peak benchmark process memory | 675.9 MB | 825.4 MB |
| All-time activity response, without envelope | 449,925 bytes | 456,380 bytes |

Cold overview measurements include first timezone-table construction. These are
local measurements, not deployed Space latency guarantees. The million-row
fixture has 15,000 artists and 120,000 artist/track identities. Its observations
extend beyond today intentionally; it is synthetic rather than listener data.

The large fixture exposed locale month formatting as the dominant initial
evolution cost. Profiling isolated that operation; ISO formatting removed it.
Minimal indexed observations and shared dimensions also avoid repeated entity
joins and per-row string duplication.

An actual Chrome pass over the running app and published history verified all
four tabs, all-time totals, mobile layout, and absence of JavaScript page errors.
Warm HTTP p95 across ten requests per endpoint was 2.27 ms for overview,
4.27 ms for activity, and 4.04 ms for rankings. Maximum observed health latency
during the cold build was 3.56 ms. The 390-pixel viewport had no horizontal page
overflow. Screenshots and reports are local, under ignored `build/reports/`.

Normal web startup hydrated the four managed checkout mirrors. Those startup
changes were restored to the original clean-branch bytes after verification;
library-data changes are not part of this release. Analytics continues reading
the verified publication independently.

## Quality evidence

- Focused domain/application/index/HTTP/web checks pass, including duplicates,
  missing albums, Unicode identity, DST, first-observed dates, incomplete cohorts,
  retrospective gaps, same-row-count correction, active readers, missing/corrupt
  history, cache deletion, and cancelled-shutdown cleanup.
- Seven Playwright scenarios pass: protected shell/data behavior; charts and
  details; URL restoration; calendar/rhythm selection; exports and hostile music
  names; mobile/keyboard use; artist filtering and racing requests.
- Ruff and package/strict business typing pass. Architecture and callback guards
  remain enforced. The exact concrete source/build `asyncio.to_thread` bridge has
  a documented standard-library reason.
- Frozen public-interface verification passes all 11 artifacts. Existing schemas
  and routes match pre-feature master after removing only new registrations.
- Wheel/source distribution build and offline wheel smoke pass. Explorer page,
  JS/CSS, chart bytes, license, and notice files are checked against source.
- Final randomized suite: **12,653 passed** in 8m30s. Independent statement/branch
  coverage: package **96.02% / 92.41%**, domain **100.00% / 99.90%**, application
  **99.66% / 98.53%**. All required floors pass. GitHub CI is being completed
  before the candidate is marked ready for review.

Browser CI uses synthetic local publications, Ubuntu 24.04, pinned npm dependencies
and Playwright Chromium, and retains screenshots/failure traces. The browser job
pins Ubuntu because `ubuntu-latest` selected Ubuntu 26.04, which the pinned
Playwright release does not support. Production gains no frontend installation
or bundling step.

## Release boundary

This is a review candidate. Deployment, deployed-Space validation, merge, branch
cleanup, and returning to clean current master follow owner review under the
project workflow. No canonical history or routine-state schema migration is
needed. Rollback removes feature code; disposable caches can simply be deleted.
