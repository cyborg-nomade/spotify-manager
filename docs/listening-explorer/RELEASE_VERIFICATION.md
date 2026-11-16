# Listening Explorer release verification

Date: 16 November 2026. Branch: `codex/lastfm-listening-explorer`.

The owner approved PR #90 on 16 November 2026 after reviewing the core and
discovery/rediscovery views together. The approved runtime was deployed and
verified before merge. Optional enrichment and Spotify actions remain follow-up
scope.

Deployed page: **https://cyborg-nomade-spotify-manager.hf.space/lastfm** (private
Space; existing application password applies). The cockpit links to the page
from its Last.fm row.

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
- Final hosted randomized suite: **12,654 passed**; the preceding local run
  passed **12,653 tests** in 8m30s before the final lifecycle regression test. Independent statement/branch
  coverage: package **96.02% / 92.41%**, domain **100.00% / 99.90%**, application
  **99.66% / 98.53%**. All required floors pass. The approved runtime commit
  `2d020766507a3f3d2a1558335b9c832d62b1d401` passed all three hosted checks in
  [PR CI run 43894640183](https://github.com/cyborg-nomade/spotify-manager/actions/runs/43894640183).

Browser CI uses synthetic local publications, Ubuntu 24.04, pinned npm dependencies
and Playwright Chromium, and retains screenshots/failure traces. The browser job
pins Ubuntu because `ubuntu-latest` selected Ubuntu 26.04, which the pinned
Playwright release does not support. Production gains no frontend installation
or bundling step.

## Release boundary

The approved runtime was deployed to Space revision
`039ae9923820d5abc69c63ced79467c3ec31eadd`, replacing code revision
`749d14d824350497dd10cb2842e08b8318aca122`. Exactly 29 runtime files were
uploaded with an optimistic parent-revision guard. Every deployed file was read
back and matched to the approved Git commit. Prior bytes were retained locally
for code rollback; no data or routine-state schema migration was needed.

Read-only preflight confirmed idle jobs and access to all four durable artifacts.
[Authenticated post-deployment verification](https://github.com/cyborg-nomade/spotify-manager/actions/runs/43950410426)
passed the existing operational checks and all new analytics checks:

- The application gate rejects data requests without the app credential.
- The cockpit link and explorer shell are served.
- Overview, calendar, rhythm, evolution, discovery, comparison, and record totals
  reconcile across the complete published history: **338,774 scrobbles**.
- Real artist detail and source-record totals agree.
- The complete-history download checksum matches the indexed source.
- Shared state is unchanged by analytical reads.

The verified source token was
`v1-e0df33ad1ba950b67dbfd05703734692683dc6029ba4e8035fbda113b049be4f`.
The durable datasets retained their pre-deploy revisions:

- State: `cba8aca7b1a0aecf23788890953175336416709c`.
- Library data: `b2c9c0d33112b1c1347e8b657c650def68df84f3`.

Production verification used an ephemeral Actions branch and the existing
read-only verification credentials. It did not run sync, mirror refresh, playlist
mutation, or state publication. The verification branch is removed after release.
The disposable analytics index can be discarded during rollback.
