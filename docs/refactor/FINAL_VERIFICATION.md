# Item 12: final compatibility verification and handover

**Status:** implemented for review on `codex/refactor-12-final-verification`,
starting from clean Item 11 merge `c90289d` on 2026-11-02. This is the **last item
in the approved backend refactor roadmap**, including the additional Item 7a.
Owner review, deployment verification, merge and cleanup remain pending.
Frontend source restructuring remains a separate future targeted refactor.

## What this item changes

This final slice adds verification and updates developer/operator documentation.
Production cleanup removes only three unreferenced, refactor-introduced private
HTTP helpers. It adds no listening rule, endpoint, retry policy, concurrency
optimization, persistence migration or dependency change. Existing expected
fixtures, normalization rules, coverage exclusions and frontend source are
unchanged.

The [architecture specification](../ARCHITECTURE_SPEC.md) gives the current
system map; [Architecture](../ARCHITECTURE.md) explains runtime ownership and
dependency direction. [Adding or changing a routine](../ADDING_A_ROUTINE.md)
shows concrete editor navigation, dependency choices and verification steps.
Historical item reports retain their original measurements and release records.

## Completion evidence

| Approved completion gate | Evidence |
| --- | --- |
| Existing assertions and compatibility scenarios retained | The complete randomized offline suite includes original tests, frozen characterization/effect traces, all routine-family differential fixtures, and accepted-write/restart recovery cases. No expected fixture was rewritten. |
| Independent coverage floors | `tests.architecture.coverage_gate` requires the exact current Python source inventory and checks statements and branches independently: package 95%/90%; domain and application each 98%/95%. Existing exclusions remain unchanged. |
| Boundary and assertion strength | Existing threshold, choice, effect, partial-write and recovery cases remain. Nine deliberate policy defects are rejected by unchanged assertions in isolated source copies; collection/setup failures cannot count as successful mutation rejection. |
| Readability, typing and dependency direction | Ruff/formatting; default strict business typing; focused strict native-adapter/tool tests; no local definitions, callback execution dependencies, inward UI/infrastructure imports, feature cycles or cross-routine private execution. New test/tool functions also pass the size/nesting audit. |
| Wire, storage and resources | All 11 frozen public artifacts match. The suite covers local/mocked-Hub revision conflicts, namespace merges, unknown fields, artifact hashes, exact bytes, publication failures, async lifetimes, task cleanup, choice/cancel races and accepted-write boundaries. |
| Offline and safe verification | Synthetic configuration, blocked sockets and protected operator files. Mutation children have their own network guard and do not contribute coverage for altered code. Package smoke uses synthetic configuration outside the checkout. No verification starts a live Spotify routine or writes shared production state/data. |
| Measured optimization parity | Item 10's unchanged request/overlap budgets, result/error ordering and cache-lifetime tests pass. Synthetic benchmark results below illustrate overlap; elapsed time is not a correctness gate or a live-service speed claim. |
| Direct paths remain visible | Existing direct-call, callback and dependency guards remain unchanged. The developer guide follows the actual album-evaluation and New Kids paths, including named application stages, domain imports and presenters. |

Final local verification on 2026-11-02:

- **11,794 tests passed**, randomized seed `20261102`, in **432.13 seconds**.
  The pre-existing Starlette TestClient dependency deprecation is the only warning.
  This includes **666 new final-verification cases** and the nine rejected mutants.
- Package: **95.70% statements** (36,533 / 38,175), **92.17% branches**
  (5,825 / 6,320), **95.20% combined**. All **686 source modules** remain measured;
  the existing **933 excluded lines** are unchanged. The three orphan removals
  account for six fewer measured statements; no module or exclusion was removed
  to change the measurement.
- Domain: **2,560 / 2,560 statements**, **886 / 886 branches**, **100% each**.
  Application: **8,782 / 8,782 statements**, **2,068 / 2,068 branches**, **100% each**.
  Every independent floor passes.
- Ruff/formatting pass across **1,128 source/test/capture files**. Package,
  automation and capture typing pass **688 files**; strict inner/native/tool/test
  typing passes **444 files**. All 23 new test/tool function signatures are
  complete; new functions pass the same 25-statement/two-indent structural audit.
- All **11 frozen public artifacts** match without changes to expected data or
  normalization. Locked installation, distribution builds and offline wheel
  inspection pass. All **244 local documentation links** resolve.

Linux CI repeats the complete suite and retains synthetic JUnit/coverage reports
on the PR. These measurements supplement, rather than replace, the frozen
workflow fixtures and their original effect/failure assertions.

## Targeted mutation checks

[`tests/verification/`](../../tests/verification/) copies only domain Python
sources and three existing policy-test modules into a temporary directory. An
unchanged control must pass first. Each mutant changes exactly one unique,
reviewed source fragment, must parse as Python and executes the same assertions.
The import origin must be the disposable copy. A rejection requires pytest's
normal test-failure status, executed tests, an assertion failure, and zero
collection/setup errors. Coverage environment variables are removed in these
children so deliberate defects cannot contaminate production coverage.

| Defect introduced only in the temporary copy | Required rejection |
| --- | --- |
| Album required-like count rounds instead of floors | Existing exact threshold cases fail. |
| Album keep boundary changes from `>=` to `>` | Exact required-like count is rejected. |
| Artist liked-track promotion changes `>= 18` to `> 18` | Exact promotion boundary fails. |
| Artist saved-release promotion changes `>= 3` to `> 3` | Exact promotion boundary fails. |
| Liked-track completeness subset test is reversed | Missing/extra membership cases fail. |
| Primary artist equality is reversed | Credited-artist filtering cases fail. |
| Successor search includes the source track | Ordered progression cases fail. |
| Saved-edition priority is reversed | Existing release ordering cases fail. |
| Missing month defaults to December instead of January | Partial-date ordering cases fail. |

All nine mutants must be killed. Three additional guard cases reject misleading
collection, setup and non-assertion failures. This is targeted assertion-strength
evidence, not an exhaustive mutation score for the entire codebase.

## Compatibility edges and cleanup

The frozen source inventory contains **654 original public module-level callable
names**. The final import guard checks all of them: **650 remain callable at
their original module/name**. Four function-valued hook APIs were already
explicitly retired in the owner-approved Item 7a callback-removal pass; this item
records their named-resource replacements rather than reintroducing callbacks:

| Original helper | Existing replacement |
| --- | --- |
| `core.state.compat.routine_state` | `core.state.compat.routine_state_from`, with named state definition/resource methods. |
| `routines.analyse_library.prepare_export_resource` | `application.library_analysis_export.prepare_export_resource`, with an analysis session. |
| `routines.analyse_library.spotify_call` | `infrastructure.library_analysis_retry.LibraryRetry` attempt scopes around direct operations. |
| `routines.review_album_limits.retry_spotify_server_errors` | `infrastructure.spotify.retry.SpotifyRetries` attempt scopes around direct operations. |

The guard checks callable availability and those four explicit migrations;
availability alone does not prove every Python signature or behavior. The
existing synchronous facade contracts, family fixtures, wire snapshots and
effect/recovery tests provide their separate evidence. Do not generalize the
four approved migrations into permission to retire other public functions.

The three removed helpers in `interfaces/http/jobs.py` are:

| Removed private helper | Why removal is safe |
| --- | --- |
| `_new_year_default_state` | Only its definition remained. `NewYearStateDefinition` already owns the registered namespace default. |
| `_create_job_log` | Only its definition remained. Named job contexts and lifecycle code already construct logs at the active clock boundary. |
| `_job_time` | Only its definition remained. Active job contexts already own timestamp observations. |

Each was introduced during this refactor and absent from the original `fbcfc65`
API source. Reference inspection covered tracked source, tests and documentation;
the frozen public inventory and live job paths remain represented. No original
public facade, SDK/file/validation leaf or measured source module is deleted.

Retained compatibility wrappers have an explicit external purpose. Concrete
legacy leaves still own original SDK expressions, serialization, validation or
binding-time contracts, described in the
[retained-helper inventory](RETAINED_LEGACY_HELPERS.md). Internal CLI/HTTP paths
skip their workflow forwarders. Required framework/standard-library function
arguments and exact private SDK captures remain narrowly recorded in the
dependency guard; interactions, retries, clocks and application stages are named
objects with direct method calls.

## Packaged entry points

`just verify-wheel` builds the source distribution and then builds the wheel
from that distribution. The offline smoke compares **all 686 Python sources and
both HTML files** byte-for-byte with the checkout. A fresh child removes checkout
source paths while retaining installed third-party dependencies, then imports
the built distribution from a temporary location. It verifies every loaded
project module/namespace originates there, both console-entry-point targets,
the **44 CLI commands**, successful CLI help, the API server's existing host/port
defaults, **119 pure API registrations**, **126 wrapped registrations**, and
packaged frontend presence. Network access is blocked before application import.

This catches missing modules or package files that an editable-checkout import
can conceal. It deliberately does not start Uvicorn, hydrate operator files or
execute a routine. The built wheel can contain the repository's existing data
assets; it is not attached to the PR or CI reports.

## Read-efficiency measurements

The unchanged offline benchmark with 80 album IDs and simulated 25 ms latency
per read reports:

| Input | Sequential requests / overlap / seconds | Native requests / overlap / seconds |
| --- | --- | --- |
| One catalog | 4 / 1 / 0.104333 | 4 / 4 / 0.026233 |
| Same catalog twice in one operation | 8 / 1 / 0.206759 | 4 / 4 / 0.026300 |

Both return the identical ordered 80 IDs. Existing contract tests also retain
the identical-batch budget of four serial reads versus one shared read. Bounded
overlap is not a Spotify quota; credential rotation, retries, dependent pages,
fresh membership and sequential writes retain their original owners and order.
See [Item 10](INDEPENDENT_READS.md) for the rationale and failure precedence.

## Reproduce and review

```console
uv sync --locked --dev
just ci-test
just test-final
just verify-wheel
uv run python docs/refactor/capture_baseline.py --write --output build/interfaces
uv run python docs/refactor/check_interfaces.py build/interfaces
just benchmark-reads --count 80 --repeat 1 --latency 0.025
just benchmark-reads --count 80 --repeat 2 --latency 0.025
```

`just test-mutations` runs the focused control/mutant assertions. The
[Backend quality workflow](../../.github/workflows/quality.yml) runs the complete
randomized suite, separate coverage floors, frozen artifacts, facade/mutation
checks and built-wheel smoke on Linux using locked dependencies, read-only
permissions and no service secrets. Synthetic JUnit and coverage reports are
retained for 14 days. The nightly production workflow is unchanged.

The branch's local preview is **http://127.0.0.1:8766/**, unlocked with any
nonempty local text. Read-only smoke checks cover health, password enforcement,
shared state, source status and all **20 reconnect endpoints**, with no job
started. The latest four operator files are retained separately, restored after
startup hydration and excluded from the implementation commit.

## Remaining limitations and separately scoped work

- Coverage, differential fixtures and mutation probes give strong regression
  evidence, not a proof for every upstream response or interleaving. Nine
  representative mutants do not establish a global mutation score. The
  pre-existing Starlette TestClient dependency deprecation remains.
- The frontend remains the original source and polling contract. A targeted
  frontend refactor needs its own plan and browser-level interaction evidence.
- Public job envelopes, inconsistent per-command defaults, retry profiles,
  exception boundaries and accepted-write recovery quirks remain as frozen.
  Broad outer job-failure guards and some concrete legacy leaves therefore
  remain; this final verification item does not rewrite their behavior.
- Job handles and the latest log window remain process-local. Durable jobs,
  stronger reconciliation of ambiguous writes, broader state batching or a new
  schema/migration system are behavior changes requiring separate approval.
- Year-specific/typo-coupled setting names and the single-operator password
  model remain. Changing public schemas, configuration or multi-user security
  is outside this refactor.
- Independent-read optimization remains conservative. No speculative workflow
  prefetching, shared cross-run metadata cache, concurrent mutations or claimed
  live-service speedup is introduced. See the
  [frozen hazards](CONTRACTS.md) and
  [architecture backlog](../ARCHITECTURE_SPEC.md#9-pending-backlog).

After this PR is approved, the only remaining approved-plan actions are the
state-preserving HF deployment and verification, PR merge, branch/worktree
cleanup and return to clean, updated `master`.
