# ADR 008: Infer sessions from gaps between selected recorded timestamps

**Status:** Proposed for owner review in Listening Sessions.
**Date:** 22 November 2026.

## Context

The approved Listening Explorer plan includes an optional session explorer after
the enrichment views. Album Quilt PR #95 was approved, deployed, verified and
merged before this increment started from clean master. Published scrobbles have
timestamps and music names, without reliable track durations, playback boundaries,
skips, completion or continuous-listening evidence.

## Decision

Use only records matching the shared local dates, artist and weekday/hour filters.
Order them by UTC timestamp and original source ordinal. Consecutive records stay
in one inferred group when their gap is at most the selected threshold. A gap
**strictly greater** starts a new group. Default to thirty minutes and accept
integer thresholds from one through 240 minutes. Preserve all duplicates and
timestamp ties. Local midnight and daylight-saving transitions do not themselves
split groups; elapsed gaps use UTC milliseconds.

These are selected-record groups. Filtering can remove context or split activity;
the first and last selected groups may continue outside the selection. Do not
assert that an edge is a verified start/stop. Mark those two groups explicitly.
A group identifier is its first recorded timestamp **within the exact history,
filters and gap definition**. It is not a universal session identity. Detail
requests must identify an actual group start in that context; an interior or
absent timestamp returns 404. The URL restores dates, timezone, artist/rhythm,
gap, minimum size, order and optional selected group.

Apply minimum recorded plays only after complete grouping. Show selected plays
and groups, matching plays and groups, and excluded plays before paginating the
matching group list. Offer most recent and most plays ordering with deterministic
recency ties. Keep the leading artist's ties in first-record order, preserving
the existing analytics artist and artist-qualified track identities.

The observed span is last minus first recorded timestamp. It includes gaps,
omits unknown playback boundaries and the final track's unknown length, and must
never be labelled time listened. A singleton has zero recorded span and unknown
duration. Show median recorded plays and median observed span for matching groups.
No completion, intent, mood or continuous activity is inferred.

Charts cover all matching groups independently of the current page. Count starts
in the local Monday-based week for ranges through 180 elapsed calendar days,
otherwise calendar month, attributing each whole group to its first selected
record. Include empty buckets. Disjoint size bands 1, 2–5, 6–10, 11–25, 26–50 and
51+ conserve both matching groups and records. Equivalent tables and CSV retain
the complete chart counts. List CSV is explicitly the current group page; detail
CSV is explicitly the current chronological source-record page.

Reuse the existing immutable SQLite index and compact artist observations. A
cohesive typed history resource adds only a bounded chronological group-record
read, retaining the exact shared filters and inclusive group timestamp bounds.
No schema migration, provider, new dependency, canonical write or job lifecycle
is needed. Named application use cases call fixed domain rules directly; sync
FastAPI endpoints and existing index acquisition run outside the event loop.

Bound derived caches to four complete grouping results and eight presentation
results, keyed by immutable resource identity and exact typed query/options.
Groups are immutable summaries; original observations are released after grouping.
Expired source generations are rejected by the existing acquisition boundary.
List pages allow at most 100 groups and detail pages at most 200 original rows.
Both additive GETs inherit the application password gate and private/no-store
policy. Only the new static module is allow-listed. Mutable explorer references
advance together to revision 7, retaining the pinned ECharts vendor asset.

PNG exports wrap the selected chart with complete source/filter context, gap,
minimum, coverage, scope and inference definitions. CSV uses the existing formula
protection and context presenter. Lock and selection changes abort obsolete
detail requests, clear their rows and invalidate in-progress PNG exports.

## Alternatives and consequences

Grouping the full source first and filtering whole sessions afterward would make
shared artist and rhythm filters describe different rows across views. Including
unselected surrounding records would also make displayed counts fail to match the
visible selection. Instead, disclose selection-scoped inference explicitly.

Automatically splitting at midnight would create artificial sessions and behave
inconsistently across display timezones. Adding track durations would introduce
new matching/provider uncertainty without establishing actual time listened.
Retaining every original record in cached groups would duplicate the history in
memory; keep summaries and read bounded original-record pages when opened.

Long gaps can reflect missing scrobbles, and short gaps can include idle time.
Changing the threshold can change a group's identity and membership. Conservative
language, exact definitions, coverage counts and original-record navigation keep
these limitations inspectable without inventing playback facts.
