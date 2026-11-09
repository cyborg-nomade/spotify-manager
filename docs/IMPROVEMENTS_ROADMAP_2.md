# Routine improvements roadmap — second round

**Approved:** 2026-11-09. The owner approved this five-item plan, its suggested
boundary rules and implementation, with the New Wine fallback below. The
[first improvements roadmap](IMPROVEMENTS_ROADMAP.md) and
[backend refactor](REFACTOR_ROADMAP.md) remain complete and closed.

## Engineering and delivery

Follow [AGENTS.md](../AGENTS.md), [ADR 003](adr/003-direct-use-case-paths.md) and
the existing architecture: native async execution, pure domain rules, direct
named application stages, explicit typed resources and bootstrap-owned wiring.
Preserve the readability, typing, function-size, dependency and lifecycle guards.
Frontend changes stay focused; source restructuring remains a separate task.

Each implementation item starts from clean, current `master` on its own
`codex/…` branch. Implement and verify, commit, open a PR and launch an isolated
local preview. Wait for owner approval before deploying or merging. After
approval, deploy only approved runtime changes while preserving independent
state/data, verify, merge and clean up before the next item. Preserve unrelated
operator files and stashes. The owner authorized committing this approved
roadmap and starting item 1; that does not approve later implementation PRs.

Use focused behavior/recovery checks and applicable lint, typing, architecture,
coverage, interface and packaging gates. Interactive changes require responsive
browser checks, including polling, cancellation and keyboard behavior where
relevant. State and automation changes need restart, concurrency and failure
checks. Update contracts only for intended changes; record release evidence and
rollback guidance in each item's guide.

## Item 1: chronological New Kids planning catalogue

**Status:** owner-approved, deployed and verified on 2026-11-09 in
[PR #85](https://github.com/cyborg-nomade/spotify-manager/pull/85). See the [item guide](improvements-2/01_NEW_KIDS_CATALOGUE_ORDER.md).

Sort the available releases oldest first, then alphabetically by title for equal
release dates. Use the same domain ordering in Queue 2 transfer and existing-artist
migration drafts, for web and CLI and every optional category. Keep canonical
edition selection and exact release identities unchanged.

For ordering only, year-only dates use January 1, month-only dates use day 1,
and unknown/invalid dates sort last. Use case-insensitive title comparison and
an exact-ID tie-break for deterministic equal-date/equal-title rows.

The current migration album remains preselected and required, at its chronological
catalogue position. The operator's selected listening order and existing saved
plans are never automatically reordered.

**Acceptance:** chronological/partial/unknown-date cases, alphabetical ties,
optional categories, current-edition retention and explicit plan preservation
work consistently in actual web and CLI interactions.

## Item 2: download stored Last.fm scrobble history

**Status:** owner-approved, deployed and verified on 2026-11-09 in
[PR #86](https://github.com/cyborg-nomade/spotify-manager/pull/86). See the
[item guide](improvements-2/02_SCROBBLE_HISTORY_DOWNLOAD.md).

Add Download beside Sync in the Last.fm row of the Data Signal Board. An
authenticated endpoint returns the latest complete, durably stored JSON history
as an attachment, using existing artifact storage and integrity checks. Download
does not trigger synchronization or reconstruct the history through JSON parsing
in the HTTP handler. A concurrent sync cannot produce a partial download.

**Acceptance:** exact downloaded contents, attachment filename, authentication,
missing-file errors, concurrent synchronization and mobile controls are verified.

## Item 3: restore the desktop Data Signal Board position

**Status:** owner-approved, deployed and verified on 2026-11-09 in
[PR #87](https://github.com/cyborg-nomade/spotify-manager/pull/87). See the
[item guide](improvements-2/03_SIGNAL_BOARD_POSITION.md).

Place the full-width board immediately below New Year's Routines on desktop as
well as mobile. Correct the desktop grid's explicit row allocation, preserving
source order, action bindings, readable controls and keyboard order.

**Acceptance:** desktop, tablet and narrow mobile layouts retain the intended
order with no horizontal overflow.

## Item 4: Flush Mode policy, shared state and panel

Add a global panel below the Data Signal Board showing effective mode, control
mode, both playlist counts, activation reason and last successful check. Provide
Check now and Automatic / Force On / Force Off controls.

| Playlist | Automatic activation | Required for automatic exit |
| --- | ---: | ---: |
| The Queue | At least 2,400 tracks | At most 1,200 tracks |
| Queue 2 | At least 1,200 tracks | At most 900 tracks |

Either activation threshold turns automatic mode on. Once active, automatic mode
stays on until both exit conditions hold. Force On/Off persists across checks,
reloads and deployments until the operator selects Automatic. The automatic
checker can still refresh observations while an override controls effective mode.

While effective mode is on, block all app actions for Found Art, Genre Reveal,
The Queue, Queue 2, Queue 3 and Sauvignon, including both queue flushes. The owner
will operate backlog flushing manually outside the app. Enforce the same policy
at backend application boundaries for web, API and CLI; disabled UI controls show
the reason. Block new starts and resumptions; already-running jobs finish normally.

New Wine normally has No Discovery checked and locked while Flush Mode is active,
with backend enforcement even if a request passes false. Outside Flush Mode,
the operator's ordinary No Discovery choice is available.

**Owner amendment:** if No Discovery cannot fill New Wine to **10 tracks**, ignore
or turn off No Discovery and permit discovery to fill the remaining slots. This
applies to ordinary manually selected No Discovery runs as well as Flush Mode.
Try the existing recovery/no-discovery sources first; discover only for the
remaining capacity. Explain the effective fallback in progress/results. Enforce
it in the backend, preserve accepted transition/recovery semantics, and reflect
it in previews. The standalone Sauvignon command remains blocked in Flush Mode;
New Wine's internal capacity fallback is the explicit exception.

Use pure domain decisions, named application use cases and a dedicated shared
state namespace. Failed count checks preserve the previous decision and expose
stale observations. Concurrent checks cannot overwrite manual overrides. Existing
routine namespaces and accepted plans remain intact.

**Acceptance:** threshold boundaries and hysteresis, persistent overrides,
failed reads, concurrency, all listed entry points (including dry runs/resumes),
New Wine's normal enforcement and under-capacity exception, restart and accurate
web status are covered. Verify sufficient recovery avoids discovery, empty and
partly filled recovery sources enable it only as needed, and lack of eligible
discovery never fabricates a full playlist.

## Item 5: nightly Flush Mode checks

Integrate the checker into the existing Berlin-time nightly workflow,
independently of Recent/Full artifact freshness. Already-current library files
must not suppress the mode check. Nightly checks update observations and
automatic state without undoing persistent overrides.

Preserve maintenance-window, retry and duplicate-trigger behavior. Deployment's
check-only workflow remains read-only. Verify the scheduled execution after
owner approval, deployment and merge.

**Acceptance:** activation, exit, overrides, stale/failed reads, repeated nightly
triggers, independent artifact freshness and maintenance boundaries are tested;
a successful live scheduled/manual automation check is recorded after approval.
