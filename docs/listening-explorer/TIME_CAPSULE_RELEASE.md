# Listening Explorer: Time Capsule release candidate

Date: 16 November 2026. Branch: `codex/listening-time-capsule`.

After approving the first explorer release, the owner authorized completing the
next release before another review handoff. PR #90 was deployed, verified and
merged as `50b7a16`; its branch and temporary verification worktree were cleaned
up before this branch started from clean, current master.

Review: **http://127.0.0.1:8765/lastfm?tab=capsule&preset=all**.
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

Ten Chrome scenarios cover existing explorer behavior plus the new tab,
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

This is the next review candidate. Under the project workflow, approval of this
PR precedes its Hugging Face deployment, deployed verification and merge. The
first approved explorer release remains deployed. No canonical history or shared
state migration is needed; rollback restores code and discards derived caches.

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
