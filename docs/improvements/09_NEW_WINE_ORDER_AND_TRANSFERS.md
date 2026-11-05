# Item 9: New Wine order and Wine Cellar confirmation

**Status:** owner-approved, deployed and verified on 2026-11-05 in
[PR #81](https://github.com/cyborg-nomade/spotify-manager/pull/81).
**Branch:** `codex/item09-new-wine-order-and-transfers`.
**Roadmap:** [Item 9](../IMPROVEMENTS_ROADMAP.md#item-9-order-new-wine-replacements-and-confirm-cellar-transfers).

## Marker order

New Wine now applies transitions within existing records before transitions that
start another record. Encounter order remains stable within both groups. For
A finishing and choosing a new record, B advancing, and C finishing and choosing
a new record, the resulting markers are **B next / A new / C new**. A different
release chosen from a single also starts a new record and belongs at the tail.
An ordinary next track, including a jump to a later liked track, stays in the
first group. Completion without another record retains its normal behavior.

Release and endpoint prompts still follow the original playlist order. Accepted
plans are checkpointed immediately, but new-record plans wait until the other
entries have been reviewed and their within-record transitions applied. A quit
can therefore leave an accepted new-record plan waiting while already completed
advances remain applied. Rerunning resumes that plan without asking for it again.
Summaries and audits show completed effects in their execution order.

The durable source snapshots, accepted plans and completion statuses determine
the remaining order after restart. There is no new queue or separate schedule to
reconstruct. Accepted appends are reconciled against live membership by the
existing executor; replacements remain secured before their sources are removed.
Destination membership is refreshed before the deferred phase, so consuming a
source during later prompts prevents that source from starting another record.
Concurrent tail entries remain intact. Preview uses projected membership.

## No-discovery cellar decisions

Web and CLI now ask before transferring each eligible Wine Cellar entry in
no-discovery mode. The proposal shows artist, record, track and the observed
library counts. The web prompt includes a Spotify album link. Existing affinity
thresholds are unchanged: at least three saved albums or eighteen liked tracks;
album qualification can avoid counting liked tracks.

- **Accept transfer** checkpoints the intent, appends when needed, and only then
  removes the cellar marker. Duplicate destination membership avoids another append.
- **Skip this run** leaves the marker in Wine Cellar, consumes no destination
  capacity, and continues to the following candidate. Its identity is persisted
  for the current active run, including repeated copies of that marker.
- **Quit** pauses the refill without accepting the current proposal. It preserves
  completed transitions and saved skips. The unaccepted candidate is offered
  again on resume. The active run is not marked completed while refill is paused.

CLI defaults to Skip. Previously skipped entries can be considered again in a new
run after the current run completes. Ineligible entries are still left in place
without a prompt. Discovery mode retains automatic ordered transfers. Python
compatibility callers without the optional transfer reader retain their original
automatic interaction contract; standard composed web and CLI runs supply it.

Acceptance rechecks that the same source observation still exists. Live execution
also refreshes destination membership and refuses a new addition if it filled
during the prompt. Changed source metadata or presence fails explicitly before
creating an intent. Preview performs the same source check and retains its
projected destination capacity. These checks do not claim a multi-playlist atomic
transaction; edits after the last observation remain subject to Spotify's API.

An already persisted pending intent, including one from the previous runtime, is
accepted authority and resumes without another prompt or affinity check. Its
append-before-removal and duplicate reconciliation remain unchanged. Cancellation
is checked before and after the new interaction and around accepted transfer
effects, including after intent persistence and after destination append. Thus a
stop can leave a recoverable intent, with its source or destination secured.

Each web transfer proposal has an opaque request identity. Missing, old,
already-consumed or wrong-kind submissions cannot accept the next candidate.
Submission and consumption use the existing owning job, lock and signals. Reload
restores the proposal; polling retains its DOM and keyboard focus. Execution-mode
controls are locked while the job is active. The existing release and canonical
endpoint request forms remain compatible.

## Architecture, state and compatibility

The application directly calls the pure `starts_new_record` domain rule and uses
the existing named planner and executor. `CellarReview` owns the invocation's
interaction state; `TransferChoiceReader` supplies explicit decisions and
cancellation. Bootstrap binds the reader alongside the existing concrete cellar
access. There are no function-shaped execution dependencies, new framework,
package, HTTP route or Spotify endpoint contract.

State remains version 1 in the existing `new_wine` namespace. Accepted plans and
statuses retain their layout. Only a live skip lazily adds `active_run.refill_skipped`,
a validated list of track IDs. Missing lists mean no prior skips; malformed
progress fails rather than silently discarding it. The active run remains
read-only in the state editor. Existing pending transfers require no migration.
Effects completed by an older runtime remain in place; the new order applies to
the remaining transitions, without moving or replaying completed markers.

The additive web contract extends the existing pending model with
`cellar_transfer`, its identity and source/count metadata, and the existing choice
request with an optional identity required for new transfer proposals. Refill
summaries add `paused`; skipped transfers appear as explicit result rows. Only
OpenAPI changes in the public baseline. All namespace defaults, existing routes,
CLI commands and Spotify contracts remain identical.

The 18 frozen cellar recordings add only `refill.paused=false` to their result
snapshots. Removing that field reproduces every original observation, including
effects, audits, checkpoints and failure recovery. Their original source
provenance is retained. Two existing API expectations add the corresponding
default pause flag and null proposal metadata.

## Owner review

Account preview: <http://127.0.0.1:8767/?review=item09>.
Offline demo: <http://127.0.0.1:8769/?review=item09>.
Unlock text: `wine-review` (any nonempty value works on loopback).
Both used isolated local state, data publications and working files. During
review, Dry run stayed checked in the account preview. These review servers were
stopped after approval and deployment.

The offline demo runs actual routes, workers, application stages and persistence
with synthetic Spotify observations. New Wine starts with Amber finishing,
Birch advancing and Cedar finishing. Wine Cellar contains Dahlia then Elm; both
qualify through three synthetic saved albums. Its Spotify links use synthetic
release IDs. Other routines are outside the fixture's scope.

1. Keep Dry run checked, enable No discovery and Run. Choose Amber's new record,
   then Cedar's. The release prompts should remain in that order.
2. At the cellar prompt, verify the artist/record/track and three saved albums.
   Reload and tab between controls; the proposal should persist with its focus
   retained across subsequent polls. Check the narrow mobile layout.
3. Skip Dahlia, then accept Elm. The result lists **Birch / Amber / Cedar** in
   execution order, Dahlia as skipped, and Elm as moved. New Wine is projected
   from three to four markers. Dry run leaves remote and durable progress intact.
4. Rerun and Quit at a release or cellar proposal, or use the panel's stop control.
   Unaccepted proposals must not transfer a marker.
5. Optional: uncheck Dry run only in the offline demo. Accepted effects change its
   simulated playlists and local files. Quitting at a cellar proposal preserves
   the ordered transitions; a subsequent Run resumes the refill and retained skips.
   The fake remote and shared state both survive process restart.

The agent's live offline verification is archived separately, and the demo has
been returned to this initial scenario for owner review. No account routine was
started during verification. Preview and synthetic files must never be uploaded.

## Verification and release

`just ci-test` passes **12,250 tests**, random-order seed **79045**, in 455.91
seconds, with **95.46%** aggregate coverage and independent domain/application
floors passing. Ruff, package typing (714 files), strict typing (466 files),
architecture, cancellation, dependency and interface checks pass. All 11 public
artifacts verify. Wheel verification passes for 714 packaged Python/frontend
files, 44 commands, 135 wrapped routes and both entry points.

Focused checks cover mixed record order, singles selecting another record,
accepted/rejected append, removal and checkpoint responses, pause/resume, live
membership changes, transfer choices, durable skips, duplicate handling, stale
submissions and actual HTTP/CLI execution. Browser verification covers the mixed
preview, per-artist proposals, both cancellation controls, reload, focus and
320/390/1120 px layouts. Preview state and simulated remote bytes stay unchanged.
A real offline process restart preserves exact state/remote bytes, ordered
markers and skipped progress, then accepts the following artist without replay.
The temporary viewport override was reset.

The owner approved PR #81 after testing on 2026-11-05. GitHub
[source CI 41987822821](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41987822821)
passed all **12,250 tests**, random-order seed **144909**, plus typing,
architecture, interface, packaging and independent coverage gates.

Authenticated [preflight 41992960415](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41992960415)
and [postflight 41993894946](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41993894946)
verified automation access, shared state, all four artifacts and no active jobs
across **20** endpoints. Neither check started a routine or history scan.

Only the **15 approved runtime files**, including two new modules, were uploaded
with a guarded parent revision and verified prior blobs. Space revision
`3da0020034b1d0c2807a3e8703195b94a10092e5` is running; all **126 cumulative release
blobs**, exact served frontend, startup, health and protected authentication were
verified. State stayed at `45f409930215adf29d185b769453b337dc478eca`; canonical data
stayed at `96c1caba1f8e6c5dadccd677cc2f1b03bed957d1`. Credentials, operational files
and all preview/synthetic state were excluded. Both owned review servers were
stopped after verifying their 20 idle endpoints; local data and operator stashes
were preserved. Remaining release tracking is documentation only; merge and
branch cleanup follow [AGENTS.md](../../AGENTS.md).

Rollback restores the prior runtime while preserving completed playlist effects
and shared state/data. An older runtime ignores the new skip list and resumes its
automatic refill/order behavior; avoid resuming an active reviewed run under the
old runtime. Retain pending intent evidence and completed markers rather than
clearing state. Stop owned idle review servers and clean the branch after merge,
preserving operator files and stashes.
