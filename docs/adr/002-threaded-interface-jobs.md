# ADR 002: explicit interface jobs during the synchronous migration

**Status:** proposed in Item 7; implementation is in progress on
`codex/refactor-07-interfaces-and-jobs`. Review the complete Item 7 PR before its
deployment or merge.

## Context

Business policies and injected use cases were extracted in Items 3–6. HTTP and
CLI delivery still contain long functions, nested callbacks, repeated polling
and conflict logic, and a large response model holding fields from many routines.
Item 7 must make those adapters readable without changing their public contracts
or starting the asynchronous transport/execution work assigned to Items 8–9.

Original behavior is asymmetric. Analysis jobs reserve by exact command, while
playlist and history jobs reserve their entire shared registry. Each registry
has its own lock. Cross-registry starts and different analysis commands can
overlap. Active phases include cancellation in progress. Terminal jobs remain
in memory; thread-dispatch failure leaves a queued handle registered. Annual
jobs initially omit the queued log that other playlist jobs produce.

Existing callers and tests use `api.py`/`main.py` imports and override seams.
OpenAPI class and handler documentation is itself part of the frozen baseline.

## Decision

Keep public compatibility facades, and move real delivery implementations into
feature modules under `interfaces/http/` and `interfaces/cli/`. Use explicit
imports and dependency arguments. Do not copy a facade's globals into another
module, generate command handlers dynamically, or introduce a workflow framework.

Place wire request/response models and result presenters in HTTP feature modules.
Keep their existing names, field ordering, defaults, validation and serialized
documentation. The wide `BlastJobResult` is a compatibility view belonging to the
HTTP adapter; it is not a business result or an application dependency. Typed
routine outcomes from the existing inner layers feed feature presenters.

Keep process-local handles, thread signals and registry locks in the HTTP adapter.
Share only transport-independent lifecycle decisions and accepted-log ordering
through `application/job_lifecycle.py`. The adapter holds the original registry
lock around selection, registration, mutation and snapshotting. It supplies
clock/presentation boundaries; the application imports no FastAPI, SDK, runtime,
threading or wire models.

Replace worker closures with small, ordinary methods on feature-owned worker
contexts. Each context receives its job handle and explicit observation,
cancellation and choice dependencies. Keep each routine's choice validation,
retry policy, effect checkpoints and finalization order. Retain the existing
last-resort worker error boundary at the compatibility edge while replacing
internal catch-all handling with specific errors.

Preserve client construction, credential rotation and synchronous dispatch in
this item. Characterize concurrent reservations, callback routing/restoration,
and signal ownership before changing shared SDK callbacks. Any callback change
must preserve accepted business effects and visible contracts under that
evidence; asynchronous client and task ownership remain Items 8–9.

## Options considered

| Option | Assessment |
| --- | --- |
| Move whole monoliths into feature files | Shortens files but retains nested callbacks and duplicated mechanics. |
| Generic workflow/job framework | Introduces more concepts than these routines require and obscures their different interaction boundaries. |
| Replace threaded jobs with async tasks now | Mixes interface migration with transport/lifetime changes assigned to later items. |
| Feature adapters with a small shared lifecycle core | Separates presentation and process-local resources while preserving routine-specific rules and override seams. Chosen. |

## Trade-offs and consequences

Compatibility exports and thin facade wrappers remain until their callers can
migrate. Original schema documentation stays unchanged even where a newly
designed model would normally receive more extensive docstrings. New public
adapter helpers and worker methods follow the project's documentation rules.

The refactor deliberately preserves process-local retention, existing conflict
scope and dispatch-failure behavior. It does not add distributed scheduling,
job pruning, cancellation rollback or a new response envelope. Sharing a small
predicate or log helper does not require making all routine transitions uniform.

Native async transport and task lifetime remain follow-up decisions. Keeping
those changes separate allows the original effects, choices and interruption
fixtures to remain useful throughout the migration.

## Evidence and actions

- [x] Capture original starts, launch arguments, overlap and phase observations
  from Item 6 merge `93a36aa` before production changes.
- [x] Replay 27 start configurations, 729 directed overlap cases and 216 phase
  decisions, plus 27 dispatch failures and four concurrent reservation cases.
- [x] Add 216 polling cases using those original phase decisions and verify
  snapshot log buffers are detached.
- [x] Extract feature wire models, 16 result presenters, process-local handles,
  active queries and initial shared lifecycle/log helpers.
- [ ] Extract worker callback contexts and explicit interaction dependencies;
  complete callback ownership and cancellation/choice race tests.
  Analysis callbacks are extracted and directly covered, including concurrent
  sink/signal ownership and the unchanged SDK hook restoration convention.
- [ ] Extract feature HTTP routers and CLI commands/renderers/prompts.
- [ ] Verify full coverage, strict typing, frozen public artifacts, dependency
  boundaries and local frontend/job behavior on the complete Item 7 branch.
- [ ] Obtain Item 7 PR approval before deployment or merge.
