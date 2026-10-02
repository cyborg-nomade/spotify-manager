# Item 7: interfaces and shared job mechanics

**Status:** in progress on `codex/refactor-07-interfaces-and-jobs`, starting from
the clean Item 6 merge `93a36aa`. Deliver the complete item in one PR, start its
local web environment for review, and await approval before deployment or merge.

The proposed delivery design is recorded in
[ADR 002](../adr/002-threaded-interface-jobs.md). Implementation remains
incremental on this branch; there is no partial Item 7 PR.

## Implemented opening increment

- Freeze original queued wire views, launch arguments, 729 directed overlaps
  and 216 phase decisions from Item 6 merge `93a36aa`, before production changes.
  Replays also protect 27 thread-start failures and four concurrent reservations.
- Check polling for each of the 27 configurations in all eight phases against
  the frozen original active-phase decisions, with detached log buffers.
- Extract wire models into feature modules under `interfaces/http/models/` and
  retain explicit compatibility imports in `api.py`. Preserve model docstrings
  because they are included in the frozen OpenAPI schemas.
- Extract 16 routine result conversions into typed HTTP feature presenters.
  Replace compound/multiline result comprehensions with explicit loops.
- Extract process-local handles into the HTTP adapter and share active-phase,
  conflict-selection, log acceptance and retention helpers through an SDK-free
  application module. Keep the existing locks, first-conflict selection order,
  empty-message behavior and sequence/factory failure boundaries.
- Replace 20 repeated active-job polling comprehensions with typed query helpers
  while retaining facade snapshot override seams and encounter order.

At this checkpoint, 1,479 focused job/API/web tests pass. The shared lifecycle
module has 100% statement and branch coverage; strict typing of the new modules
and support tests passes. All 11 frozen public artifacts match after the model
and presenter extraction. Worker, router and CLI extraction are still pending.

The opening increment also passes the full randomized suite: 10,284 tests with
seed `20261002`, 96.28% package statement coverage and 92.38% branch coverage.
Domain/application statements and branches remain 100%. Package mypy passes
for 472 files; Ruff and formatting pass. The separate post-extraction capture
still matches all 11 original public artifacts. This evidence applies to the
opening increment, not to later unverified changes or a complete Item 7 release.

## Analysis worker increment

The analysis worker now uses a feature-owned `AnalysisWorker` context with
ordinary methods for progress, logging, retry waiting, dispatch and outcome
presentation. Its facade keeps the original scheduler target, expected exception
handling, last-resort error boundary and callback restoration before completion
timestamping. Client construction and shared SDK hook semantics are unchanged.

Direct tests cover all four dispatch paths, missing clients/resources, repeated
progress, unknown or smaller totals, cancellation detail, empty messages, retry
resume/cancellation, optional rate-limit timestamps, outcome logs, SDK hook
binding/restoration and concurrent callback/signal ownership. The 28 tests provide
100% statement and branch coverage of the new worker. Frozen interface artifacts
still match. Other worker families and CLI adapters remain pending. Router
registration is separated in the next increment below.

## HTTP router increment

The 115 original API registrations are now declared in 24 feature router
factories under `interfaces/http/routers/`. `api.py` supplies its original public
handler functions explicitly and includes the routers in their original encounter
order. Factories own fresh routers; no handler is generated or rebound through
copied globals. Existing dependency signatures, response models, status codes,
handler names and documentation remain unchanged.

The locked FastAPI represents included routers as lazy route contexts. The audit
capture now observes their effective metadata, retaining nested prefixes,
methods, hidden routes and declared response/status information. Tests check
direct, included and nested registrations, so router extraction cannot make the
audit silently omit public endpoints. The original baseline is unchanged and
the complete comparison still verifies all 11 public artifacts.

The existing 1,507 job/API/web tests pass after registration moves. Three direct
audit tests also pass; router factories and audit tests pass strict typing. The
remaining HTTP handler logic, worker families and CLI extraction are pending.

## Following a frontend request

Route declarations now provide the first backend entry point when searching for
a URL used in `frontend/index.html`. They name the existing facade handler,
whose signature still owns the framework's validation and dependency overrides.
For a library-analysis start and its later polling:

| Step | Location to follow |
| --- | --- |
| Frontend request and polling | `spotify_manager/frontend/index.html` |
| URL, HTTP method, accepted status and response model | `interfaces/http/routers/analysis.py` |
| Public handlers, reservation and scheduler target | `api.py`: `cmd_analyse_library_*`, `start_analysis_job`, `_run_analysis_job` |
| Job-owned progress, cancellation/retry callbacks and outcome presentation | `interfaces/http/analysis_worker.py` |
| Existing use-case composition and compatibility seams | `routines/analyse_library.py`, `bootstrap/library_analysis.py` |
| Typed use-case stages and pure business rules | `application/library_analysis_*.py`, `domain/library_analysis*.py` |
| External implementations and return views | `infrastructure/library_analysis_*.py`, `interfaces/http/models/analysis.py` |

Other feature routers follow the same facade entry pattern. Their worker/CLI
implementation extraction is still in progress; do not assume all logic has
already moved out of `api.py` and `main.py`.

## History CLI increment

The `update-scrobble-history` command now delegates to a feature-owned
`interfaces/cli/history.py` adapter with explicit configuration, reader factory,
refresh and presenter dependencies. Its ordinary `echo` method replaces the
event lambda. The public command keeps its original Typer signature, flags, help
text, console/settings creation order and facade override seams.

The summary renderer preserves original table rows, formatting and persistence
messages. Configuration errors still precede client construction; construction
errors remain outside the guarded refresh boundary. Two added tests exercise
construction-time event routing and uncaught construction failure. With the
original CLI tests, 99 tests pass and cover the new module's statements and
branches at 100%. Strict typing passes and all 11 frozen public artifacts still
match. Other CLI command/prompt/rendering families remain in progress.

## Implementation sequence

1. Characterize existing starts, asymmetric conflicts, command/ID guards,
   queued snapshots, worker launch arguments and failure boundaries. Freeze
   original observations before changing production handlers.
2. Add typed, directly testable job records/events and explicit cancellation and
   choice channels. Keep process-local lifetime, 250-entry logs, detached
   snapshots and existing safe cancellation boundaries.
3. Move actual common reservation, lookup, log, choice, cancellation and terminal
   cleanup mechanics into a shared lifecycle service. Preserve each feature's
   conflict scope, validation order and status transitions.
4. Split HTTP models, presenters, workers and routes by feature. Keep the wide
   public response envelope through presenters and retain compatibility exports
   and dependency-override seams in `api.py`.
5. Split CLI handlers, prompts and renderers by feature, retaining `main.py` as
   the public entry point and preserving all 44 command signatures and output.
6. Test every routine adapter, concurrent job reservations, callback ownership,
   accepted-effect cancellation, choice races and cleanup. Remove mutable shared
   callbacks only after the applicable compatibility/resource evidence passes.
7. Run isolated gates, randomized full coverage, strict typing, readability and
   dependency checks, CLI/OpenAPI comparisons, and local frontend/job smoke tests.

## Compatibility constraints

Execution remains synchronous/threaded during Item 7. Native async clients and
task lifetime conversion remain Items 8–9. No persistent worker queue, new
distributed locking, new job retention policy or response schema is introduced.

The two existing registries differ: analyses reject matching active commands;
playlist/history starts reject active jobs across their shared registry. The
annual workflow has no initial queued log, unlike the other playlist starts.
Queue 3 import and flush share the same wire command but differ in their worker
arguments and annual-only field. Preserve these details rather than making
the lifecycle mechanically uniform.

Public route names, schemas, validation, statuses and body fields remain frozen.
Moving implementation modules may change private Python source locations; any
comparison-tool allowance must apply only to that internal location and must
continue rejecting changes in public endpoint identity or behavior. Original
baseline files are never rewritten to the new implementation.

Existing API/CLI tests rely on facade callback and dependency override seams.
Keep these through explicit composition rather than dynamically copying module
globals or generating handlers at runtime. New/refactored functions remain
top-level or ordinary methods, short, flat, fully typed and documented.

## Release starting point

Item 6 is running as Space revision `ffa7c4c9e7f162e6066e9a227775495fb259d48c`.
The authenticated release check passed with no active jobs. Before Item 7 changes,
the package has 9,049 passing tests and separate coverage of 96.13% statements and
91.66% branches; domain/application coverage is 100%.

The pre-existing production nightly artists refresh reports invalid JSON in
`YourLibrary.json`. It occurred on the Item 5 deployment before this release.
The authenticated artifact/state checks pass; Item 7 does not silently change
that source-export behavior or repair production data as part of interface work.
