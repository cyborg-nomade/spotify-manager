# Item 7: feature interfaces and shared job mechanics

**Status:** implemented and ready for PR review on
`codex/refactor-07-interfaces-and-jobs`, starting from the deployed Item 6 merge
`93a36aa`. Deployment and merge require Item 7 PR approval.

The design and compatibility trade-offs are in
[ADR 002](../adr/002-threaded-interface-jobs.md). Business rules and use cases
remain in the domain/application layers extracted in Items 3–6.

## Delivery boundaries

| Responsibility | Implementation |
| --- | --- |
| Stable imports, framework signatures, overrides and explicit composition | `api.py`, `main.py` |
| Original URL/method/status/model registrations | 24 feature factories in `interfaces/http/routers/` |
| HTTP validation, submission, cancellation and response presentation | 24 feature adapters in `interfaces/http/handlers/` |
| Original request/response schemas | `interfaces/http/models/` |
| Typed routine outcome to original JSON conversion | `interfaces/http/presenters/` |
| Job-owned callbacks, interactions, outcomes and cleanup | `interfaces/http/analysis_worker.py`, 18 contexts in `interfaces/http/workers/` |
| Process-local handles and separate cancellation/submission signals | `interfaces/http/job_records.py` |
| Locked lookup, conflict responses and registration-before-snapshot | `interfaces/http/job_registry.py` |
| Ordered active snapshots and bounded playlist retries | `interfaces/http/job_queries.py`, `interfaces/http/playlist_retry.py` |
| SDK-free active-phase, accepted-log and submission polling rules | `application/job_lifecycle.py` |
| CLI execution, prompts, errors and rendering | 25 contexts in `interfaces/cli/features/`, plus `interfaces/cli/history.py` |

The facade supplies explicit dependencies to fresh command/handler contexts.
Workers use ordinary methods bound to their own handles and signals. Common
mechanics are small named helpers; each feature retains its visible choices,
status transitions and effect boundaries. No runtime handler generation, copied
module globals or workflow framework is introduced.

## Behavior retained

- All 44 CLI commands and 115 API registrations retain signatures, options,
  defaults, help/schema documentation, response fields and encounter order.
  Web additions, password middleware and dependency overrides remain.
- Analysis conflicts are scoped to the exact command; playlist/history starts
  share their original registry. Different analysis commands and starts in
  separate registries can overlap. First-conflict selection remains lazy and
  ordered, with the original 409 detail.
- Slot checks, construction, initial logs, registration and detached snapshots
  stay under the original lock. Dispatch follows registration. Snapshot and
  thread-start failures retain the queued handle; annual jobs retain their
  original absence of a queued log.
- `queued`, `running`, `waiting` and `cancelling` remain active. Terminal handles
  remain retained in process memory.
- Empty log text is rejected before observing its clock/factory. Accepted logs
  advance sequence numbers and then retain the latest 250 entries. Polling
  returns detached models and log buffers.
- Choice validation and submission remain atomic. Cancellation wakes the
  original signals, clears the original pending view, and preserves accepted
  effects/checkpoints. An accepted token or order stays stored until its safe
  consumption boundary.
- Submission polling still waits 0.5 seconds before checking cancellation and
  consuming a value. Empty strings and empty tuples retain their non-`None`
  meaning. Retry timing, prompt stop/restart and callback restoration order
  remain unchanged.
- SDK construction, caches, credential rotation and threaded dispatch are
  preserved. Existing last-resort worker and CLI rotation/token-refresh error
  boundaries remain for compatibility; new business handling uses specific errors.

Public facade and schema docstrings are frozen interface data. Their text stays
unchanged; new adapters use Google-style documentation. The wide `BlastJobResult`
remains an HTTP compatibility view populated from typed routine outcomes, with
no dependency from the business layers on rendering or wire models.

## Original evidence and verification

`tests/fixtures/refactor/job_lifecycle_original.json` was captured from Item 6
**before** production extraction and remains unchanged. Replays cover 27 launch
configurations, 729 directed overlaps, 216 phase decisions, 27 thread-start
failures, four real concurrent reservations and 216 detached polling cases.
The original 11 public artifacts in `docs/refactor/baseline/` also remain unchanged.

Additional tests cover analysis callback/signal ownership and SDK restoration,
routine adapter success/error/cancellation paths, constructor-time CLI event
routing and failure boundaries, lazy/nested router inventory, and real concurrent
choice/cancellation endpoints. The 27 interaction tests and 27 snapshot-failure
tests also pass against an isolated checkout of `93a36aa`.

Final verification on the complete implementation:

- Full randomized suite: **10,373 passed**, seed `20261005`.
- Package coverage: **96.44% statements** (29,854 / 30,955) and **92.66% branches**
  (5,369 / 5,794), above the approved 95% / 90% gates.
- Domain/application statement and branch coverage: **100%**. Separate isolated
  gates also pass: **1,201 domain** and **3,622 application** tests.
- Package mypy: **576 files**. All extracted interfaces, shared lifecycle and
  new ownership/baseline tests pass strict typing.
- Ruff and formatting pass. Structural audit finds no local functions/classes,
  lambdas, multiline/compound comprehensions or functions above 25 executable
  statements in the extracted interface scope; control nesting is at most two.
- A separate final capture still matches all **11 frozen public artifacts**.
  The original baseline, dependency inventory and lifecycle fixture are unchanged.
- Local browser: health is online; **4 / 4 sources** and shared state load; all
  20 active-job reconnect endpoints return 200; terminal visibility and reload
  followed by local unlock work without console warnings/errors. No live routine
  or Spotify write was initiated by the smoke checks.

Local review is available at **http://127.0.0.1:8766/**. Enter any non-empty text
at the local gate. Startup hydrated the four canonical local data files through
the existing read path; those runtime changes are excluded from the code commit.
The earlier preserved runtime stash remains intact.

## Following a frontend request

For a library-analysis start and later polling:

| Step | Location |
| --- | --- |
| Frontend request and polling | `spotify_manager/frontend/index.html` |
| URL, method, accepted status and model | `interfaces/http/routers/analysis.py` |
| Stable framework signature and supplied dependencies | `api.py`: `cmd_analyse_library_*`, named handler factory |
| Request delegation and poll/cancel response | `interfaces/http/handlers/analysis.py` |
| Start composition and reservation | `api.py`: `start_analysis_job`; `interfaces/http/job_registry.py` |
| Job-owned execution, progress, retry and cleanup | `interfaces/http/analysis_worker.py` |
| Compatibility and use-case composition | `routines/analyse_library.py`, `bootstrap/library_analysis.py` |
| Typed use cases and pure business rules | `application/library_analysis_*.py`, `domain/library_analysis*.py` |
| External implementations | `infrastructure/library_analysis_*.py` |
| Return path | Typed summary → feature presenter → job view → detached poll response → frontend |

Other routers follow the same entry pattern; their workers are under
`interfaces/http/workers/`. For a CLI operation, start at its Typer command in
`main.py`, follow its context in `interfaces/cli/features/`, then the routine
facade/bootstrap into application/domain.

## Review and release

The complete item is delivered in one PR. Its local web environment runs on this
branch so the owner can test before approving. After approval, deploy to Hugging
Face and verify, merge, preserve unrelated runtime data during cleanup, and
return to clean, current `master` before the next item.

Native async transport and task/client ownership remain Items 8–9. The known
pre-existing invalid production `YourLibrary.json` export is not rewritten by
this interface refactor.
