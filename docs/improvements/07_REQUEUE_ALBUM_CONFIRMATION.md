# Item 7: confirm the next Requeue album

**Status:** implemented, owner-approved, deployed and verified on 2026-11-04.
**Release:** [PR #79](https://github.com/cyborg-nomade/spotify-manager/pull/79).
**Approved runtime:** `f47f99c7af56c987a394066cc87e48f4fbfb31e5`.
**Space revision:** `4853f3b1d01fabfb957afd3737e98eebd0516e08`.
**Branch:** `codex/item07-requeue-album-confirmation`.
**Roadmap:** [Item 7](../IMPROVEMENTS_ROADMAP.md#item-7-confirm-the-next-album-in-requeue-for-a-dream).

## Behavior

Web and CLI now review each proposed next eligible studio album or EP before a
transition:

- **Accept album:** use its first playable track as the replacement marker.
- **Skip album:** offer its chronological successor without loading its tracks.
- **Cancel:** abandon selection and keep the current marker unchanged.

The prompt shows artist, proposed album, release type/date, track count, Spotify
album link and the current release/track. The CLI pauses its spinner during input
and defaults an empty answer to cancellation. The web keeps its preview/live mode
locked while the job is active and restores that mode after reload.

Repeated skips continue until acceptance, cancellation or exhaustion. Both
interfaces explain the existing completion policy before a skip: rejecting all
remaining eligible albums completes the artist and removes the current marker
in a live run. Dry run previews that removal. Completion after repeated skips has
the explicit reason `all remaining eligible albums were skipped`.

An already-final eligible source keeps its existing completion outcome without
inventing another album proposal. An ineligible current release and an empty
playlist keep their existing skip/empty outcomes. Accepting an album without
playable tracks keeps the existing no-change skip outcome; the operator can
instead skip that album and review its successor. Release eligibility, preferred
edition selection and chronological ordering are unchanged.

## Mutation and recovery

Selections and skips have no Spotify effects. After live acceptance or exhaustion,
the application reads the playlist again before any mutation. A changed or missing
head aborts with the existing changed-playlist error. With an unchanged head,
duplicate membership and playlist counts are recomputed from this fresh read:
concurrently adding the selected marker avoids a duplicate, and concurrently
removing it no longer causes the replacement to be omitted.

The replacement is still appended before removing the source. Existing accepted
append/interrupted removal recovery remains supported: rerunning reviews the
successor again, recognizes the already-present target and finishes removal
without another append. Accepted removal and audit failures retain the routine's
existing recovery semantics; this item does not add a durable transition journal.

Cancel closes selection without a playlist effect or completed-transition audit.
The job cancellation endpoint also wakes a waiting interaction, clears its prompt
and takes precedence over an unconsumed choice. Dry run suppresses the final live
recheck, playlist effects and audit writes, as before.

Pending choices are held in the existing process-local job registry. Reload and
reconnection retain them while that worker is running. Cancellation or process
restart abandons an unapplied selection; a new run starts from the actual current
playlist head and offers its next successor again. Album skips are not persisted
as artist preferences. No state schema migration or data backfill is needed.

## Architecture and contracts

The application calls the named `RequeueAlbumSelection` stage with a catalog,
`RequeueAlbumReader` and progress resource. Fixed transition, cancellation and
fresh duplicate decisions remain directly imported domain rules. Bootstrap owns
concrete adapters and web/CLI resources own their interactions. No new framework,
function-shaped production execution dependency or service lookup is introduced.

Web and CLI explicitly supply the album reader. Python compatibility callers
without one keep their original automatic transition and ordered read/effect
contract. Existing frozen Requeue effect traces remain unchanged.

The additive web contract consists of:

- `requeue_pending_choice` on the existing job model, including a fresh opaque
  `request_id` and album/source metadata;
- `POST /commands/flush-requeue-for-a-dream-jobs/{job_id}/choice`, requiring that
  request identity and `accept`, `skip` or `cancel`; and
- summary action `cancel` for an explicitly abandoned selection, surfaced as a
  cancelled web job with the original playlist counts.

Missing identities or invalid actions fail request validation. An old identity,
already-consumed choice, cancelled job or wrong owning command cannot select an
album. Submission and consumption use the existing job lock and signals. Each
proposal has a fresh identity, so a late click cannot accept a following album.
Polling preserves the current prompt's DOM, including keyboard focus.

Only the OpenAPI schema, one HTTP route and its public interface inventory are
updated in the baseline. Existing route evidence and Spotify endpoint contracts
are retained. The job lifecycle fixture adds only a null pending-choice field to
**21** playlist snapshots; removing that field reproduces every original value.
Its original source provenance is preserved. The endpoint-count guards explicitly
increase to **124** API handlers and **135** total wrapped routes.

## Owner review

Account preview: <http://127.0.0.1:8767/?review=item07>.
Offline demo: <http://127.0.0.1:8769/?review=item07>.
Unlock text: `requeue-review` (any nonempty value works on loopback).
Both environments use isolated local state, data publications and working files.
Keep Dry run checked in the account preview. The offline demo uses actual routes,
workers and application/domain stages with synthetic Spotify observations and
in-memory playlist effects; it makes no live service calls. Its Spotify links
refer to synthetic releases. Other routines are outside the demo catalog's scope.

1. Run the offline demo with Dry run checked. Skip the second and third albums,
   then accept the fourth. Check its first playable marker and unchanged playlist
   count in the result.
2. Run another preview and skip all three successors. Check the explicit
   exhaustion reason and previewed marker removal.
3. Skip one album, then Cancel. Rerun and confirm the second album is offered
   again. The simulated source marker should remain unchanged.
4. Reload while waiting. Check the same proposal and run mode return. Tab between
   controls; polling should retain focus. Use the panel's stop control while
   waiting and check the prompt clears.
5. To test effects, uncheck Dry run in the offline demo and accept one successor.
   This changes only the simulated playlist. The next run starts from that new
   marker, and exhaustion follows the same completion policy.

## Verification and release

Verification on the review branch includes:

- `just ci-test`: **12,088 passed**, random-order seed **502669**, in 461.36
  seconds. Ruff, package typing, strict inner-layer typing, architecture checks
  and independent coverage gates passed. Aggregate coverage is **95.36%**; the
  package and domain/application statement/branch floors remain satisfied.
- **151 focused tests** passed for album review, stale submissions, cancellation
  races and capture portability. **1,253 lifecycle/path tests** passed with all
  prior observations retained apart from the intentional additive field.
- Existing application/routine tests and vertical slices retain accepted effects,
  noninteractive behavior, interrupted-append recovery and audit boundaries.
  New checks cover repeated skips, exhaustion, cancel/restart, conflicting starts,
  changed heads, concurrent tail edits, empty successors and dry-run isolation.
- All **11 public artifacts** passed, including retained Spotify endpoint
  contracts. Only the new route, its inventory and additive schema changed.
- `just verify-wheel` passed with **704** exact packaged Python/frontend files,
  **44** commands and **135** wrapped routes, including both entry points.
- Browser checks passed acceptance after two skips, exhaustion, both cancellation
  controls, reload, keyboard focus and **320/390/1120** px layouts. The temporary
  viewport override was reset. Both local servers match all **704** runtime files,
  return healthy responses, expose the required choice contract and have **20**
  idle job-list endpoints. Account verification did not start a Spotify job.

The owner approved PR #79 after testing the local previews on 2026-11-04.
GitHub [source CI 41888937944](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41888937944)
passed all **12,088 tests**, random-order seed **904348**, plus typing,
architecture, interface, packaging and independent coverage gates.

Authenticated [preflight 41890953299](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41890953299)
and [postflight 41891330110](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41891330110)
verified automation access, shared state, all four artifacts and no active jobs
across **20** endpoints. Neither check started a history scan or playlist routine.

Only the **15 approved runtime files** were uploaded, including two new modules,
with a guarded parent revision and verified prior blobs. All **101 cumulative
release blobs**, the running Space revision, exact served frontend, startup and
health were verified. The protected API still requires application authentication.
State stayed at `ae471c85f97417a46f1076a43c52d10cf3a4b7b2`; canonical data stayed at
`e70e0a3af6017f702decd5f0d5738944faf01084`. Credentials and unrelated operational
files were excluded. Remaining release-tracking changes are documentation only;
merge and cleanup follow [AGENTS.md](../../AGENTS.md).

Rollback restores the preceding runtime/frontend. There is no durable selection
state to migrate backward; stop or cancel process-local review jobs before
replacing the runtime. Completed playlist effects and unrelated data publications
must not be reverted during a code rollback. Stop the owned idle review servers
and clean the item branch after merge, preserving operator files and stashes.
