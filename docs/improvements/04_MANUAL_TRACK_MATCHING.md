# Item 4: manual Spotify matching for historical tracks

**Status:** implemented, verified and owner-approved on 2026-11-04.
**Release:** [PR #76](https://github.com/cyborg-nomade/spotify-manager/pull/76).
**Approved runtime source:** `033883bb58c381191b5a8cd77db701c06153ef00`.
**Branch:** `codex/item04-manual-track-matching`.
**Roadmap:** [Item 4](../IMPROVEMENTS_ROADMAP.md#item-4-add-manual-matching-to-blast-and-daily-mind-radio).

## Behavior and scope

Blast from the Past and Daily Mind Radio retain their existing automatic artist,
track, album and liked-track qualification and ranking. Several qualifying
results still use that ranking; the new interaction begins only when no
automatic result qualifies.

For an unresolved play, Spotify receives one broad track search using the
available artist, track and album text. Up to ten usable results from the first
ten search positions are shown in their original order. Manual results retain
all artist credits, album title and a Spotify link. Similarity and exact-artist
requirements do not filter them. Invalid metadata rows are omitted without
pulling results from below the first ten positions. Malformed search pages remain
errors rather than being interpreted as empty results.

The operator selects a result, explicitly chooses **No match**, or cancels the
routine. Empty results still require a no-match or cancellation decision. A
selection gets a fresh liked-status observation for the final result; it does
not need to pass automatic qualification. The displayed `qualifying_matches`
count continues to describe the automatic candidates. Existing playlist
membership and first-selection duplicate rules apply to manual selections too.
Rejecting one play continues the batch. Cancelling at a matching prompt aborts
the batch before its playlist append stage.

Dry run uses the same manual choices to produce a complete preview and suppresses
playlist writes. As before, its final playlist length is the actual unchanged
length; its added count describes the proposed additions.

Only these two web/CLI commands opt into the fallback in this item. The separate
Blast Artists command and other Last.fm consumers keep their behavior. Item 5
will integrate the reusable stage into the remaining consumers and investigate
the reported New Year's Chevelle case. Noninteractive Python compatibility
calls retain their prior behavior when no interaction resource is supplied.

## Architecture and interaction protocol

The existing `HistoricalResolution` stage performs automatic searches and the
shared liked observation first. It calls the named `ManualTrackMatching` stage
for unresolved plays. Bootstrap constructs that stage with a concrete Spotify
catalog, the invocation's retry/cancellation resources, and the web or CLI
interaction owner. There are no supplied execution callbacks, new dependencies,
client factories in routines, or frontend source restructuring.

The web job publishes `track_match_pending_choice` in its existing reconnectable
view. Each prompt has a fresh request ID. The two new choice endpoints are:

- `POST /commands/blast-from-the-past-jobs/{job_id}/choice`
- `POST /commands/daily-mind-radio-jobs/{job_id}/choice`

Their JSON request is `{"request_id": "…", "choice": "spotify-id"}`; an empty
choice string explicitly means no match. Under the existing job lock, the
handler validates command ownership, waiting status, request identity and offered
track membership. Stale/repeated requests receive 409; unoffered tracks receive
400. Cancellation wins before worker consumption. Pending prompts survive page
reload within the same server process, and polling preserves keyboard focus by
retaining the DOM for an unchanged request ID.

As with other existing interactive jobs, pending work is process-local. A server
restart does not resume the interaction. No selected-match cache or durable
state schema is introduced.

The CLI suspends its progress display, prints the numbered results and links,
and accepts a number, `n` for no match or `q` to cancel. It does not default to a
selection. The existing interruptible terminal resource owns input.

The intentional contract updates are the two additive routes, three matching
wire models, the nullable pending-choice field in the shared job view, route
counts, and that field in the 21 existing queued playlist wire snapshots. Other
snapshot values and assertions remain intact. The Spotify endpoint inventory
and all other captured artifacts remain unchanged after source-line normalization.

## Review and verification

Review used <http://127.0.0.1:8767/?review=item04>, using
`track-matching-review` to unlock it (any nonempty text works at loopback).
Its working files and local state/data stores are isolated from production.
Leave Dry run checked when testing against your Spotify account.

A second environment at <http://127.0.0.1:8769/?review=item04> used the same real
application and job handlers with synthetic Spotify and randomness resources.
It makes no live account or Random.org requests and is suitable for reviewing
the interaction without spending Spotify requests. It uses the same unlock text.
Its catalog entries and Spotify links are synthetic review data.

1. Start Blast with Count 1. Automatic matching fails in the synthetic environment;
   inspect the candidates, full credits, albums and links.
2. Reload while waiting. The same prompt and candidate order should return.
3. Select a numbered result and check the completed dry-run preview.
4. Start Daily Mind Radio, reject its first play, then select a result for the
   following play. Both outcomes should appear in the final preview.
5. Start another run and cancel from the pending choice. It should leave no
   pending prompt and perform no playlist writes.
6. Check a narrow mobile viewport and tab from a candidate to its Spotify link.
   Polling should retain focus while waiting.

Completed checks:

- `just ci-test`: **11,904 passed**, seed `6115`, 445.36 seconds. Package and
  strict inner-layer typing, Ruff, architecture checks and independent statement
  and branch coverage gates pass. The existing Starlette TestClient deprecation
  warning remains.
- A subsequent CLI display check prevents URL truncation in an 80-column
  terminal. **30 focused CLI/interface tests** pass, including the new copyable
  URL and complete-credit regression. Final package typing and Ruff pass too.
- **11 public artifacts** match after the documented additive contract updates.
  No existing endpoint, parameter, other schema or semantic Spotify call changes
  are included.
- `just verify-wheel` verifies **695 packaged Python/frontend files**, **44 CLI
  commands**, **128 wrapped routes**, imports and both entry points.
- Real web workers and CLI commands cover automatic ambiguity, manual selection,
  rejection, cancellation, fewer than ten, ten and empty results, duplicates,
  liked-status presentation and both preview/write boundaries. Choice/cancel
  races retain atomic outcomes for both routines.
- Browser checks cover selection, rejection, empty results, cancellation in both
  routines, same-request reconnection after reload and keyboard focus through
  polling. Ten-result lists fit at 320, 390, 760, 1120 and 1440 pixels. A separate
  390-pixel check verifies all three shorter-list options and both decisions
  remain inside the viewport with no horizontal overflow.
- Both isolated servers serve the exact branch frontend, pass health checks,
  and have no active jobs across all 20 reconnectable job-list endpoints.
  Browser verification made no live Spotify, Last.fm or Random.org requests.

The owner approved PR #76 on 2026-11-04. GitHub CI run
[41780321211](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41780321211)
passed both jobs for the exact approved runtime source. The following release
tracking changes affect documentation only.

The approved 18 runtime files were deployed to private Space revision
`3bfbfd05522372a9de8123292dd6261c78c24dca`. The running revision, all 27 runtime
blobs from Items 1–4, exact served HTML and health endpoint were verified.
Shared state stayed at `622d1ac69df56633e40288c2345df9e37c1ec8e7`; canonical data
stayed at `d8c6e548758f1a134c9d2bed65edf1cd2f0e6d60`.

Authenticated preflight
[41800583689](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41800583689)
and postflight
[41800859827](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41800859827)
verified automation access, shared state, all four durable artifacts and no active
jobs across 20 endpoints. Neither check started history scans or playlist work.
Local browser verification and the owner's approval cover the interactive flow.
The PR release record tracks merge and final cleanup. Temporary review servers
are stopped during that cleanup.

## Release and rollback

The owner authorized deployment and merge, following
[AGENTS.md](../../AGENTS.md) and [DEPLOY.md](../../DEPLOY.md). Only the approved
runtime files were uploaded; operational data, OAuth caches and credentials were
preserved.
Check active jobs before deployment, the running revision and served frontend,
authentication, shared artifacts, idle endpoints and reconnection afterward.

No data or state migration is needed. Rollback restores the prior runtime files
and frontend; it does not roll back independent data publications. After merge,
stop both owned idle preview servers and remove the item branch, preserving
unrelated files and operator stashes before returning to current `master`.
