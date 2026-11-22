# Listening Explorer: Listening Sessions review

Date: 22 November 2026. Branch: `codex/listening-sessions`.
Status: implementation candidate; owner review precedes deployment and merge.

Album Quilt PR #95 was approved and deployed to private Hugging Face revision
`e8e80d09d7f83b7be2ef0bc9a987077f8d0f0c31` before merge
`c9805ba46e3d324167f209fae9e2ba193ffb08ed`. All 28 runtime/dependency files
matched approved source, durable authorities stayed unchanged, production views
reconciled 339,401 plays, and 31 health checks over fifteen minutes had no failures.
Its final CI passed before merge. This increment starts from that clean master.

## Behavior and definitions

The **Sessions** tab groups consecutive selected records using a configurable
one-to-240-minute gap, default thirty. A gap strictly exceeding the threshold
starts a new group; equality stays together. Duplicates and equal timestamps
remain separate plays, sorted by original source order. UTC gaps make grouping
independent of local midnight and daylight-saving clock changes.

Shared date, artist and rhythm filters apply before grouping. This is inference
within the visible selected records: filters can split activity and cut its
edges. First/last selected groups are marked without asserting playback starts
or stops. A group's first timestamp identifies it only within the complete pinned
source/filter/gap context; changing that context may invalidate the identifier.

Minimum plays filters complete groups afterward. Coverage reconciles all selected
plays/groups, matching plays/groups and below-minimum plays. List pages show up
to 25 groups, with most recent/most plays ordering. Medians describe matching
groups before pagination. An observed first-to-last timestamp span includes gaps
and is **not time listened**. Singletons have zero span and unknown duration.

Session-start charts include empty weeks for selections through 180 elapsed days,
otherwise empty calendar months. Each group belongs to its first record's local
bucket. The size chart uses disjoint inclusive play-count bands. Both charts and
their equivalent tables cover all matching groups, independently of list pages.

Open a group for chronological source records, original names, artist history,
stable source row numbers and independent pagination. Gap, minimum, ordering,
dates, timezone, artist/rhythm and an opened group restore from the URL. Lock or
selection changes clear rows, abort obsolete requests and invalidate old exports.

CSV distinguishes the current group page, the current original-record page and
complete chart data. Formula protection and complete source/filter/definition
context are retained. PNG wraps each chart with the full source version, filters,
gap, minimum, scope, counts and inference limits. See
[ADR 008](../adr/008-recorded-listening-sessions.md).

## Operations and compatibility

No new provider, external metadata request, dependency, canonical write or schema
migration is introduced. History/tag/country/cover caches and job lifecycles are
unchanged. Four grouping and eight presentation results bound derived reuse;
only immutable group summaries are retained. Original records are read in bounded
pages from the exact immutable history generation, with unchanged filters.

Two additive protected GET routes inherit the existing history token and gate:

| Route | Purpose |
| --- | --- |
| `/lastfm/analytics/sessions` | Exact selected/matching counts, charts and bounded group page. |
| `/lastfm/analytics/sessions/{first_ms}/records` | Actual group's definition and bounded chronological original records. |

The list accepts `gap_minutes` 1–240, `minimum_plays` 1–100,000,000, `order`
`recent`/`plays`, positive page and limit 1–100. Records require an actual group
start in the selected context, the same gap, positive page and limit 1–200.
Invalid parameters return 422; absent group starts return 404; expired history
returns 409; existing history-read failure behavior remains unchanged.
All data responses are private/no-store. Mutable explorer references advance to
revision 7; ECharts stays pinned. Only `sessions-v1.js` becomes an open static
asset. Existing endpoint operations/schemas and other public contracts remain
unchanged; source inventories stay frozen.

## Verification and preview

Hand-counted domain tests cover strict/equal gaps, duplicates, deterministic leader
ties, qualified identities, source disorder, midnight, both Berlin DST changes,
timezone display, minimum-size coverage, medians, ordering, pagination, all size
band boundaries and empty/excluded selections. Concrete use-case and HTTP tests
cover selection-scoped records, original source ordinals, 200-row bounds,
correction with unchanged source size, all gates, invalid inputs and expired IDs.

Browser checks exercise actual controls changing group counts, restored URLs and
opened records, independent page navigation, safe hostile names, formula-safe CSV,
complete-chart exports, PNG downloads, mobile layout, empty results, recovery and
locking during delayed reads. Complete regression, architecture, typing,
interface and installed-wheel results are recorded in the PR before review.

Local review uses an installed wheel with hydration and caches outside source
mirrors. The launcher explicitly sets and prints password **`preview`**. The final
PR handoff records the live URL and measured real-history counts. This feature
requires no provider test or additional music-data disclosure.


The complete local regression passes **13,005 tests**, with all independent
statement and branch floors. The new domain rules and application use cases
have 100% statement/branch coverage in 53 focused checks. Architecture/bootstrap
verification passes 460 checks, package typing checks 801 files and strict
business/test typing checks 533 files. All eleven public artifact comparisons
pass, with exactly two additive routes and all preceding operations/schemas
unchanged. The isolated wheel verifies 817 Python/frontend files, both entry
points and all 45 commands.

Independent raw-source reconciliation confirms all 339,401 published plays:

| Gap | Inferred groups | Groups with at least three plays | Plays in those groups |
| --- | --- | --- | --- |
| 15 minutes | 25,297 | 19,585 | 331,951 |
| 30 minutes | 18,520 | 15,638 | 335,611 |
| 60 minutes | 13,760 | 12,051 | 337,147 |

Every top-100 group boundary/count and every source record in the largest group
at each threshold agrees with an independent sort/partition of the verified raw
publication. Chart group/record totals, medians, 200-row pages and both new gates
reconcile. Canonical bytes and shared state are unchanged; all 25 prior tag and
eight country observations remain available, and no cover lookup was started.

A separate synthetic local process groups one million compact observations into
50,000 twenty-record groups in 0.429 seconds; presentation takes 0.069 seconds,
with a 171.9-MiB peak for that process. This measures pure grouping/presentation,
excluding source parsing, SQLite, network and deployed latency. It is not a Space
performance claim. Real-history first measured requests at 15/30/60 minutes take
1.148 / 0.491 / 0.477 seconds locally; cache warmth and a concurrent regression
run affect these observations.

All 26 browser scenarios and seven pure JavaScript checks pass, including the
preceding explorer views. Both installed-wheel previews were inspected with real
control changes, visible coverage, chart placement above the list and original
record navigation. PNG definitions and source/footer text were visually checked.
Session charts draw without animation so immediate exports use completed bars.

Real-history review: **http://127.0.0.1:8765/lastfm?tab=sessions&preset=all**.
Labelled synthetic review: **http://127.0.0.1:8766/lastfm?tab=sessions&preset=all**.
Password for both: **`preview`**, explicitly set and printed by each launcher.
The real preview uses the verified publication, with hydration/caches outside
source mirrors. The sample explicitly labels its synthetic history and metadata.
The candidate remains undeployed and unmerged pending owner approval.

The PNG timing regression compares immediate and settled exports with motion
allowed; session bars remain complete without waiting for animation. Album Quilt
post-merge checks also pass in runs 45044916187 and 45044922953.
