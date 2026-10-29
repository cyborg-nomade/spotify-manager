# Item 9: async execution and interaction

**Status:** implemented for review on `codex/refactor-09-async-execution`, based
on Item 8 merge `6ea10e4`. Deployment and merge require this item's approval.
Frontend source restructuring remains outside this roadmap.

## Start here when following a request

The route remains beside its endpoint in [`api.py`](../../spotify_manager/api.py).
Follow the named feature handler or direct application call, then the named
application stage, its directly imported domain rule, and the interface presenter.
The change to `await` makes external I/O explicit without introducing a dispatcher
or replacing the direct paths established in Item 7a.

| Path | Concrete navigation |
| --- | --- |
| Album evaluation | `api.album_evaluation` → `application.album_review.review_album` → the directly imported album policies → the endpoint's existing response construction. `bootstrap.listening.album_review_ports` constructs resources before the use case executes. |
| New Kids job | `api` route → `handlers.discovery` → `jobs.start_new_kids_job` → `NewKidsWorker.run` / `_execute` → `interfaces.operations.new_kids.flush_new_kids` / `_flush_review_playlist` → `DiscoveryRun.prepare`, `DiscoveryReview.review`, `DiscoveryRun.finish`. These application stages call the fixed domain rules directly; the worker calls the discovery presenters. |
| Operator choice | A named worker's `choose` method publishes the pending choice → `application.job_lifecycle.await_submission` awaits that job's signal → the existing choice endpoint validates and records the reply → the same worker resumes. |
| CLI | A synchronous Typer command parses its original options → `run_cli` awaits the explicitly named CLI feature method → the same application stages and domain rules → CLI presentation. |

The family inventory in [the Item 7a guide](CALL_PATH_SIMPLIFICATION.md) still
identifies the owners. Native application calls now await their I/O ports;
domain rules remain ordinary synchronous functions. Resource methods handle
external observations and effects; adapters do not conceal another application
stage. Small immutable options and named resource objects remain the inputs.

## One owner for each execution lifetime

`bootstrap.execution.ExecutionRuntime` owns native clients, admitted background
jobs, and a bounded allowance for remaining blocking resources. It creates clients
lazily on its active loop. Web lifespan enters one runtime; `ExecutionMiddleware`
binds the same owner and worker allowance to request tasks and their child jobs.
CLI commands enter one runtime inside one top-level `asyncio.run` boundary.
No pooled client crosses an event loop or survives its owner's shutdown.

Standard, library-analysis and interactive clients share an HTTP pool and
credential-refresh owners. Their original retry/rotation profiles remain
separate. Comparison's original per-identity client scope uses a fresh profile
over the owned pool. This preserves independent credential selection without
constructing another pool for every identity.

Job registration still happens before scheduling. `JobTasks` retains the named
coroutine independently of the initiating request. Shutdown requests the existing
safe cancellation signal and drains admitted work before closing clients.
Cancelling a request does not cancel a job that it has already registered.
Process-local job registries and their existing conflict scope remain unchanged.

Genre state access uses a lifespan-owned async lock. Release-state restore and
release-check submission share a separate async lock, preserving their mutual
exclusion. Registry locks cover only short synchronous inspections or updates;
no synchronous lock is held while awaiting a file transaction. The existing
nonblocking Genre Reveal run reservation still returns its original 409.

## Waits, accepted writes and complete file operations

Choices and retry delays use awaited signals. `AsyncSignal` preserves set/clear,
timeout and queued-notification behavior, including notification from a worker
thread. Each signal belongs to one waiting loop. A job's cancellation still takes
effect at its original workflow boundary: an accepted Spotify write can finish
before its checkpoint or restart reconciliation proceeds. Mutations and dependent
cursor pages remain sequential; Item 10 owns independent-read optimizations.

Complete synchronous SDK, Last.fm, filesystem, Hub and terminal operations use
bounded resource adapters. Capacity remains occupied until admitted work finishes,
even when the awaiting task receives repeated cancellation. Cancelling a file
write does not release its slot while that write is still running. Cancellation
also closes any unstarted coroutine returned by a drained compatibility resource.
Original serializers, schema validation, revision checks, backup kernels and
publication order remain in their existing synchronous implementations.

State and library administration keep prompts, confirmation and presentation on
the async CLI path. Only complete storage operations run in workers. Native
application stages and entire CLI workflows are never submitted to a worker.
The real terminal path supports Ctrl-C while waiting for input; it retains the
caller's standard-input owner. Existing in-memory input overrides remain usable.

Every required `asyncio.to_thread` argument is recorded by exact owner and resource
method in [`async_io_boundaries.json`](../../tests/async_execution/fixtures/async_io_boundaries.json).
The callback guard rejects undocumented methods even when their types are unknown.
OAuth/cache calls retain their separate exact SDK allowance. These are required
standard-library call shapes, not a general callback or thread-stage exemption.

## Retained synchronous Python APIs

The 127 routine entry points and 22 processor functions retain their original
synchronous names, signatures, defaults and completed return values. Explicit
`async_*` counterparts support native callers. Internal web/CLI/application paths
use the native methods directly rather than traversing these compatibility APIs.
Caller-supplied SDK clients and resource overrides remain caller-owned.

`run_python` is the outer synchronous compatibility boundary. With no running
caller loop, it owns and closes a private loop directly. When a synchronous API
is called from inside an existing async caller, a single private thread owns that
API's loop and receives a copy of the caller's context. The synchronous call
continues to block until its original result is available; it does not nest,
replace or close the caller's event loop. Native web and CLI execution do not use
this bridge. `ThreadPoolExecutor.submit(context.run, asyncio.run, coroutine)` is
permitted only at this exact boundary because those standard-library APIs require
functions as arguments; arbitrary executor stage dispatch is rejected.

Named `python_compat` views adapt original synchronous file, history, operator,
retry and SDK resources. They call explicit source methods and await a native
result if the supplied resource already implements one. Only concrete SDK edges
retain private method captures whose original lookup time is observable: the
saved-resource getter captured for a scan and the optional event setter captured
when subscribing. `SpotifyOffsetPages` retains the named legacy reader object;
it does not capture that adapter's bound method.

## Compatibility evidence and reproduction

Frozen expected behavior fixtures and frontend source are unchanged. Original
routine tests execute their synchronous public APIs; application and HTTP tests
exercise the native async paths. Differential traces retain decisions, ordered
requests, mutations, checkpoints, audits, visible messages and error prefixes.
Additional barriers cover pool ownership, cross-loop rejection, shutdown during
construction, overlapping job output, choice/cancel races, accepted-write restart,
queued state transactions, real terminal interruption and synchronous overrides.
No live Spotify write is part of verification.

```console
just test-async-execution
.venv/bin/pytest tests --random-order --random-order-seed=91027 -q --cov=spotify_manager --cov-branch --cov-report=json:/tmp/item9-coverage.json
.venv/bin/ruff check spotify_manager tests docs/refactor
.venv/bin/ruff format --check spotify_manager tests docs/refactor
.venv/bin/mypy spotify_manager
.venv/bin/mypy --strict spotify_manager/domain tests/domain
.venv/bin/mypy --strict spotify_manager/application tests/application
.venv/bin/python docs/refactor/capture_baseline.py --write --output /tmp/item9-interface-review
.venv/bin/python docs/refactor/check_interfaces.py /tmp/item9-interface-review
```

The checker still verifies 11 public artifacts against the original baseline.
Its only additional source normalization recognizes exactly one native comparison
album-read site alongside the retained Python comparison site. These are
alternative callers of the same original per-ID read. Method, arguments, payload
and multiplicity remain checked; a second added native site fails the checker.
Original source inventories remain historical evidence and are not regenerated
to accept the migration.

Final verification on 2026-10-28:

- **10,976 tests passed**, randomized seed `91027`, in 401.02 seconds. The existing
  Starlette TestClient dependency deprecation warning is the only warning.
- Package statement coverage: **95.69%** (36,415 / 38,057); branch coverage:
  **92.15%** (5,774 / 6,266). Combined coverage is **95.19%**. Statement and branch
  metrics separately clear the approved gates; no coverage exclusions were added.
- Domain: **100%** statements (2,560) and branches (886). Application: **100%**
  statements (8,762) and branches (2,054).
- `just test-async-execution` passes **286 tests**, Ruff/formatting and strict
  typing for **47 files**. It includes the exact callback-boundary guard and the
  prohibition on synchronous locks spanning an await.
- Package and standalone nightly-script typing pass **685 files**. Strict domain,
  application, native transport and their tests pass **410 files**; the additional
  bounded-I/O ledger also passes strict typing. Full Ruff and formatting pass.
- All **11 frozen public artifacts** match. Original expected behavior fixtures,
  interface baselines and frontend source are unchanged. The updated guide's
  relative documentation links resolve.
- Both source distribution and wheel build successfully from the final tree.
  No live Spotify writes or production data are used by the regression suite.

The local review smoke checks cover health, password enforcement, source status,
shared state and all **20 reconnect endpoints**, with no active jobs. The four
retained operator files are restored after startup hydration and verified by
hash. These local review changes are excluded from the implementation commit.

## Local review and following items

The local review environment runs the item branch at **http://127.0.0.1:8766/**.
Use any non-empty local unlock text. Existing routine-specific dry-run history,
cache and audit effects still apply. Operator runtime files are retained separately
from the implementation commit.

Item 10 measures request counts and optimizes only proven independent reads.
Items 11 and 12 finish architecture/type enforcement and final compatibility
verification. This item makes no measured live-service speedup claim.
