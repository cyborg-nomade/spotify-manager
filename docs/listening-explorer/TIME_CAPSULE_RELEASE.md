# Listening Explorer: Time Capsule release verification

Date: 17 November 2026. Branch: `codex/listening-time-capsule`.

After approving the first explorer release, the owner authorized completing the
next release before another review handoff. PR #90 was deployed, verified and
merged as `50b7a16`; its branch and temporary verification worktree were cleaned
up before this branch started from clean, current master.

Deployed: **https://cyborg-nomade-spotify-manager.hf.space/lastfm?tab=capsule&preset=all**
(private Space; existing application password applies).

Local review: **http://127.0.0.1:8765/lastfm?tab=capsule&preset=all**.
The normal web application runs from the candidate wheel in an isolated temporary
installation. The local review password is **`preview`**, printed at each start.
Startup hydration writes into that installation, preserving the
source checkout's managed mirrors. Review uses the actual published archive.

## Delivered scope

- **On This Day:** earlier anniversaries of the selected Through date, across
  available history independently of From. Artist and timezone filters apply.
  Leap days are never shifted; current/future years are excluded.
- **Musical Eras:** weighted Jaccard similarity across complete artist-share
  vectors. Listening volume does not affect identical mixes. Empty comparisons
  are undefined, including their diagonals. Months are used through 240 months;
  longer selections use explicit calendar years without truncating history.
- Source coverage, zero recorded days and partial boundary periods are explicit.
- A heatmap, anniversary bars, accessible tables, reference-period selection,
  matrix zoom, URL restoration, and original-record drill-down are included.
- CSV exports contain the full similarity matrix or anniversary rows with
  coverage and source context. Both charts export PNG.
- Two additive, protected GET endpoints: `/lastfm/analytics/eras` and
  `/lastfm/analytics/on-this-day`. Both retain pinned generation envelopes and
  private no-store responses. Anniversaries reject rhythm filters; the Time
  Capsule tab clears those filters explicitly.

All existing routes and OpenAPI schemas were compared to the preceding release
and preserved. Only two endpoint declarations and their new result models were
added to the frozen contracts. Source/dependency inventories remain frozen.
The existing read-only index resource, bootstrap wiring and source identity are
reused. No new canonical storage, enrichment service or music API is needed.

## Verification

Hand-calculated tests cover share similarity, volume invariance, artists beyond
the top eight, symmetry, empty periods, timezone conversion, leap days, visible
start independence, earlier-year scope, source coverage, partial boundaries,
yearly fallback and generation separation. The new domain rules have **100%
statement and branch coverage**. Application, HTTP and existing web checks pass.

Eleven Chrome scenarios cover existing explorer behavior plus the new tab,
actual heatmap clicks, visible chart dimensions, URL reference restoration,
CSV/PNG, hostile music names, long/empty selections, mobile layout and record
navigation. Desktop/mobile screenshots were inspected. Browser CI uses only
synthetic published data; personal screenshots remain local and ignored.

Ruff, package and strict business typing, architecture/callback guards and all
11 frozen-interface artifacts pass. Wheel smoke verifies **771 packaged
Python/frontend files** against source and both existing entry points. The full
randomized suite and independent coverage floors are also required; the PR's
checks and description record their final results.

Post-merge CI for the first release exposed a test readiness race: the helper
allowed roughly half a second for a correct background index build. A controlled
two-second build reproduced that failure. The candidate replaces the attempt
count with a ten-second monotonic deadline, fails immediately on a reported
source error, and includes the delayed-build regression. Production execution is
unchanged by this test-only correction.

## Published history and scale

The read-only benchmark verified the current published artifact: **338,774
scrobbles**, published 16 November 2026 at 20:14:02 UTC, checksum
`e0df33ad1ba950b67dbfd05703734692683dc6029ba4e8035fbda113b049be4f`.

| Local measurement | Published archive | Synthetic million rows |
| --- | ---: | ---: |
| Index build | 2.42 s | 6.08 s |
| Cold eras, including result serialization | 0.69 s | 5.98 s |
| Cold anniversaries, including serialization | 0.39 s | 0.99 s |
| Eras response before HTTP envelope | 477,496 bytes | 384,410 bytes |
| Peak benchmark process memory | 737 MB | 852 MB |

The million-row fixture spans about 19 years and 15,000 artists. Similarity only
accumulates intersecting artist keys, and the symmetric matrix is computed once
per pair. The larger cold-query cost is visible rather than hidden behind a
listening-duration estimate or a truncated artist list.

The initial Time Capsule wheel check in Chrome reconciled all 229 monthly totals to the published
338,774 observations, rendered 52,441 matrix positions, and reported no page
errors or horizontal overflow at 390 pixels. First complete cold page load was
6.52 seconds locally, including verified source acquisition and index build.
These measurements do not establish deployed Space latency.

## Release boundary

The owner approved PR #91 on 17 November 2026 after reviewing the readability
changes and the existing-browser cache correction. The approved runtime was
deployed and verified before merge. No canonical history or shared-state
migration was needed; rollback restores code and discards derived caches.

## Readability revision after owner review

The cockpit Explore link now matches the surrounding button dimensions,
typography and pressed effect, with blue shading. Musical Eras replaces its
continuous gradient with six fixed bands, subdues self-comparisons, and adds a
threshold highlight control. A Group similar periods toggle uses deterministic
average linkage on the existing scores, with empty periods at the end.
It reorders both axes, reference choices, tables and CSV consistently; underlying
counts and similarity values are preserved. Grouping and threshold restore from
the URL and appear in exports. No analytical HTTP contract changes are needed.

Seven pure JavaScript checks validate the presentation algorithm. The new Chrome
scenario uses a hand-calculated matrix to verify rendered band colors, gray
self-comparisons, actual opacity, original-index click mapping, grouped CSV data,
keyboard adjustment, saved settings and mobile resizing. Existing explorer
browser scenarios remain required. The new data-free JavaScript helper receives
one exact static allowlist entry. Local review setup now always announces
password `preview`; this preference is recorded in AGENTS.md.

## Existing-browser cache correction

Owner testing in an already open Firefox tab reproduced a mixed-version page:
new controls were visible, but cached older scripts still rendered the continuous
gradient and did not wire those controls. A hard refresh restored the new code,
confirming the cause. Fresh Chrome sessions had not exercised that upgrade path.

The shell and mutable assets now require cache revalidation. The stylesheet,
entry script and all local module imports use an explicit matching revision
query, bypassing previously cached unversioned URLs. The pinned vendor chart
asset remains immutable. Eight HTTP cases check the cache policies. A new Chrome
regression first proves that old scripts/styles remain cached after its fixture
cookie is removed, then loads the current page and verifies grouping and
highlighting work without clearing the cache. Source data and API contracts are
unchanged.

## Approved deployment

Approved runtime commit: `a2493567c527b7b001f3f6c60f780b9ea1ec28fd`.
All three [hosted quality checks](https://github.com/cyborg-nomade/spotify-manager/actions/runs/44058408535)
pass: **12,679 randomized tests**, independent statement/branch coverage floors,
eleven Chrome scenarios, seven pure JavaScript checks, typing, architecture,
frozen contracts and wheel packaging.

Space revision `375836dd33bfcd6227010de29ed4fde568262fe8` replaces
`039ae9923820d5abc69c63ced79467c3ec31eadd`. Exactly **13 runtime files** were
uploaded in one code-only commit with an optimistic parent guard. Every file
was read back and matched to the approved source. Prior bytes were retained
locally for rollback; credentials, canonical files and operational state were
excluded from the upload.

The [read-only preflight](https://github.com/cyborg-nomade/spotify-manager/actions/runs/44064031103)
confirmed healthy authentication, shared state and all four durable artifacts,
with no active jobs across 20 routine endpoints. The
[authenticated deployed verification](https://github.com/cyborg-nomade/spotify-manager/actions/runs/44064403189)
then passed:

- Application gate, cockpit link, new controls, revised asset URLs and cache
  revalidation policy.
- All existing analytical totals: **338,774 scrobbles**, plus entity details
  and original-record pagination.
- Musical Eras: all **229 monthly periods**, complete-source totals, matrix
  dimensions, symmetry, self-comparisons and score bounds.
- An independent raw-record reconciliation of the complete artist-share
  weighted similarity for June 2014 versus June 2024.
- Every earlier anniversary against the original records, and independence
  from the visible From date.
- Complete-history yearly fallback over 2000–2040 without truncating data.
- Published-history download checksum and unchanged shared state after reads.

Verified source:
`v1-e0df33ad1ba950b67dbfd05703734692683dc6029ba4e8035fbda113b049be4f`.
The durable authorities retained their predeployment revisions:

- State: `804f0a4ce4c5b3599740e3dc08f63feeb732091e`.
- Library data: `e228e54d4a2057cceffd4ef210e0186d6da273fd`.

The Space remains private. Verification uses existing read-only Actions
credentials on a temporary branch; it does not run refreshes, synchronization,
playlist changes or state publication. The verification branch and worktree
are removed after release.
