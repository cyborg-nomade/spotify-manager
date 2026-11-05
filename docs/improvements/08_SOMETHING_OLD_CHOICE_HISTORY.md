# Item 8: previous Something Old choices

**Status:** owner-approved, deployed and verified on 2026-11-05 in
[PR #80](https://github.com/cyborg-nomade/spotify-manager/pull/80).
**Branch:** `codex/item08-something-old-choice-history`.
**Roadmap:** [Item 8](../IMPROVEMENTS_ROADMAP.md#item-8-show-previous-something-old-choices).

## Behavior

Something Old, Something New now shows recorded use beside its three source
options in web and CLI: Last.fm top tracks, Spotify popular tracks, and an album
or EP. Each option shows its completed-selection count and most recent recorded
date. Album history includes the most recent album name. The prompt also names
the most recent recorded choice across all modes. Dates use UTC calendar dates.

This history is informational. It neither chooses a mode nor disables previously
used options. The original explicit operator decision and CLI default remain in
place. An option without evidence says **No recorded use**; it does not claim the
artist has never used that option. A missing history says **No recorded choices
for this Spotify artist**. Imported or interruption-recovered evidence is labelled.

History joins on the accepted Spotify artist ID. Artist renames and changing
Last.fm spellings retain that identity's history, while same-name artists with
different Spotify IDs remain separate. The currently accepted artist mapping
determines which history is shown. No historical artist mapping is guessed from
names alone.

Only a complete live append counts as a new completed choice. A preview, artist
or mode cancellation, abandoned album choice, explicit no-match outcome, failed
empty-playlist recheck or partial append does not count. Dry run can display
existing evidence and usable audit imports in a detached view, without changing
the shared choice history. The existing preview behavior for history refresh and
playlist selection remains unchanged.

## State, import and interruption recovery

The new `something_old_choices` namespace has version 1 and two separate maps:

- `choices`: completed events keyed by a deterministic selection fingerprint;
- `pending`: unconfirmed append intents keyed by destination playlist.

An event retains the Spotify artist ID and name, original Last.fm label, explicit
mode, aware selection timestamp, playlist ID, complete ordered selected track
IDs, optional album identity/name and evidence provenance. The fingerprint uses
artist ID, mode, normalized timestamp, playlist and ordered track IDs. It ignores
display labels and provenance, deduplicating a completed append, its audit import
and later recovery. Event dates retain the routine's original effective selection
timestamp; no new clock reads change the existing summary/audit contract.

The original empty-playlist recheck still happens before any append. A live
nonempty selection then checkpoints its intent before the first Spotify write.
Cancellation is checked before and after this new checkpoint, so a stop during
persistence cannot authorize an append. A completely accepted append is recorded
in shared history before the separate existing audit write. An audit failure
therefore cannot lose already accepted history. A failed intent checkpoint
prevents Spotify writes; an accepted checkpoint with a lost response remains
recoverable.

The next invocation reconciles a pending intent before the original nonempty
playlist early return. A matching completed audit is sufficient evidence. Without
one, the complete current playlist must match the full selected track multiset,
including duplicate multiplicity. Unknown items, extra or missing tracks, partial
appends, inconsistent totals and incomplete/repeating pages cannot prove a
completed selection. Reconciliation never replays the append. A partial or changed
nonempty playlist keeps its intent unconfirmed; an empty playlist discards that
unproven intent without counting it. If an interrupted append was consumed or
changed before it could be verified and has no usable completion audit, its past
completion cannot be inferred safely.

Available legacy `something_old_log.jsonl` records are scanned at invocation time.
Only complete `added` records with an explicit Spotify identity, valid mode,
aware timestamp, originally empty destination and complete track count are
imported. Preview, incomplete, malformed, unmapped and unknown-mode records are
excluded. Repeated imports do not increment counts again, and an existing applied
event keeps its stronger provenance. Missing audit files mean no available audit
evidence; unreadable files and malformed shared history fail explicitly instead
of replacing history with an empty value. No missing historical logs are
reconstructed or claimed to be complete.

The namespace uses the existing conflict-aware shared-state service, so completed
history survives process restart and deployment. A conflicting same-namespace
write fails before silently replacing another writer's evidence; unrelated
namespaces remain intact. It is created lazily, without resetting shared state or
backfilling other data. The state editor exposes the namespace with its version,
completed records and pending intents read-only. Its validator rejects invalid
versions, mismatched event/destination keys and incomplete evidence.

## Architecture and compatibility

`SomethingOld` calls the named `SomethingOldChoiceHistory` stage for loading,
prior usage, intent and completion. Fixed fingerprint and aggregation rules are
directly imported domain functions. The storage resource owns namespace, audit
and fresh playlist observations. Bootstrap constructs those concrete resources;
business stages do not construct clients or locate services.

Web/CLI supply a named history-aware mode reader. Existing custom mode readers
keep their two-argument interface; normal composed runs still retain successful
history. Direct application callers without the optional history stage preserve
their original complete-run traces. Existing ranking, artist matching, track
selection, empty-playlist authority, append batches and legacy audit bytes remain
unchanged. No existing frozen Something Old trace was rewritten.

The existing pending-choice model adds `previous_modes` and
`previous_choice_summary`. Per-mode entries carry counts, dates, album name,
provenance and a shared readable label. No route, CLI command or Spotify endpoint
contract changes. Polling preserves a stable pending prompt's DOM and keyboard
focus, and reload restores the current prompt and locked preview/live mode.
Option metadata inherits the button's readable text colour within this panel.

The public baseline changes only OpenAPI and the additive namespace default;
all prior namespace defaults and endpoint contracts remain identical. The
baseline capture identifies this new native definition directly while retaining
every old legacy validator binding. The callback guard records one narrow
standard-library requirement: `asyncio.to_thread` needs the concrete audit reader
at its bounded file-I/O edge. No function-shaped business execution dependency,
workflow framework or new package is introduced.

## Owner review

Account preview: <http://127.0.0.1:8767/?review=item08>.
Offline demo: <http://127.0.0.1:8769/?review=item08>.
Unlock text: `choice-history-review` (any nonempty value works on loopback).
Both environments use isolated local state, data publications and working files.
Keep Dry run checked in the account preview. Its existing destination must be
empty before the routine offers a mode, as before.

The offline demo uses actual routes, workers, application stages and persistence
with synthetic Spotify/Last.fm observations. It makes no live service calls for
this routine. It starts with two recorded Last.fm choices, including one usable
audit import, one Spotify-track choice and no recorded album choice. Spotify is
the most recent recorded mode. The available audit import is detached in preview
and becomes durable only in a live invocation. Other routines are outside this
fixture's scope.

1. Run the offline demo with Dry run checked. Verify the counts **2 / 1 / 0**,
   the dates and imported-audit label, and the most recent Spotify choice.
2. Preview each of the three modes. After each preview, run again: counts and
   the most recent recorded choice should remain unchanged. Album mode still
   asks which studio album/EP to use.
3. Quit at the mode or album prompt, or use the panel's stop control. No new
   choice should appear afterward.
4. Reload while waiting and tab between options. The same history/mode should
   return, and polling should retain focus. Check the narrow mobile layout.
5. To test a completed choice, uncheck Dry run in the offline demo and select a
   mode. Only its in-memory Spotify playlist and local history change. Its next
   run reports the nonempty playlist, retaining the original guard. Automated
   checks cover consuming that selection, rerunning and seeing the increased
   count, as well as new-service/restart and interrupted-effect recovery.

## Verification and release

The final `just ci-test` passes **12,170 tests** (random-order seed **320440**,
462 seconds), with **95.43%** aggregate coverage and both independent domain and
application coverage floors passing. Ruff and package typing pass; package typing
covers 712 files and the strict check covers 461 files.

The **79 focused tests** cover all three modes, preview/abandonment exclusion,
stable IDs, audit import/deduplication,
accepted and rejected checkpoints, partial and duplicate appends, cancellation
at the new persistence boundary, audit failure, malformed state, shared conflicts,
fresh runtime construction, actual web/CLI execution and history labels. Another
433 existing compatibility, architecture, bootstrap, state and API checks pass.
All 11 public artifacts verify, with only the additive OpenAPI and namespace
default changes described above. Wheel verification passes for 712 packaged
Python/frontend files, 44 commands, 135 wrapped routes and both entry points.

Browser checks cover recorded counts/dates/provenance, most recent mode, all three
previews, quit and job cancellation, reload, focus retention and 320/390/1120 px
layouts. All three previews leave the stored history bytes unchanged. A real
offline process restart preserves those bytes and returns the same counts.
Both isolated review runtimes match all 712 Python/frontend files on the branch,
pass health and contract checks, and have no active jobs across all 20 job-list
endpoints after verification.

The owner approved PR #80 after testing on 2026-11-05. GitHub
[source CI 41909178559](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41909178559)
passed all **12,170 tests**, random-order seed **64524**, plus typing,
architecture, interface, packaging and independent coverage gates.

Authenticated [preflight 41981684998](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41981684998)
and [postflight 41981895891](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41981895891)
verified automation access, shared state, all four artifacts and no active jobs
across **20** endpoints. Neither check started a routine or history scan.

Only the **18 approved runtime files**, including eight new modules, were uploaded
with a guarded parent revision and verified prior blobs. Space revision
`4ff6afb8b99438baf8f48519da71cc76c660235e` is running; all **112 cumulative release
blobs**, exact served frontend, startup, health and protected authentication were
verified. State stayed at `45f409930215adf29d185b769453b337dc478eca`; canonical data
stayed at `96c1caba1f8e6c5dadccd677cc2f1b03bed957d1`. Credentials, operational files
and all preview/synthetic state were excluded. Both owned review servers were
stopped after verifying their 20 idle endpoints; their local data and operator
stashes were preserved. Remaining release tracking is documentation only;
merge and branch cleanup follow [AGENTS.md](../../AGENTS.md).

Rollback restores the preceding runtime/frontend while retaining the new
namespace and all completed playlist effects. Cancel active jobs before replacing
the runtime. An older runtime does not add or reconcile this new choice history;
keep its evidence intact until the new runtime returns. Do not clear pending
evidence or revert independent data during a code rollback. Stop the owned idle
review servers and clean the branch after merge, preserving operator data.
