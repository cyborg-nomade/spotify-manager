# Adding or changing a routine

Start at the caller and follow named calls. Put listening decisions in `domain/`,
sequencing and recovery in `application/`, concrete resources in `infrastructure/`,
construction in `bootstrap/`, and validation/presentation in `interfaces/`.
The application imports fixed domain rules directly. No dispatcher or registry
is needed to choose a business function at runtime.

## Follow an existing request

For a short example, open [`api.py`](../spotify_manager/api.py) and find
`GET /albums/evaluation`. The decorator sits beside `album_evaluation`:

1. `interfaces.http.handlers.lookups.album_request` validates references and builds
   the typed `AlbumReviewRequest`.
2. `bootstrap.listening.album_review_ports` constructs the catalog and membership
   resources. Construction finishes before business execution starts.
3. [`application.album_review.review_album`](../spotify_manager/application/album_review.py)
   resolves the album, awaits ordered tracks and fresh liked status, then calls
   [`domain.albums.assess_album`](../spotify_manager/domain/albums.py) directly.
4. The domain returns `AlbumAssessment`; the application returns `AlbumReview`.
5. Back in the endpoint,
   [`interfaces.presenters.albums.album_evaluation`](../spotify_manager/interfaces/presenters/albums.py)
   constructs the existing wire model. The endpoint translates its existing
   upstream error and returns that model.

Ctrl-clicking the use case and its domain imports follows the decision path;
port methods lead to resource contracts, with their concrete construction in
`bootstrap/listening.py`. Resource methods read or write external facts. They do
not secretly execute another application stage.

For an interactive path, find `POST /commands/flush-new-kids` in `api.py`:

```text
api.cmd_flush_new_kids
  → interfaces.http.handlers.discovery.cmd_flush_new_kids
  → interfaces.http.jobs.start_new_kids_job
  → interfaces.http.workers.new_kids.NewKidsWorker.run / _execute
  → interfaces.operations.new_kids.flush_new_kids / _flush_review_playlist
  → application.discovery_run.DiscoveryRun.prepare
  → application.discovery_review.DiscoveryReview.review
  → application.new_kids_planner.NewKidsPlanner
  → domain.progression / domain.discovery_progression rules
  ← application result and summary
  ← NewKidsWorker._completed and interfaces.http.presenters.discovery
  ← existing job result, polled by the cockpit
```

This path needs a job owner, interaction and accepted checkpoints. Keep those
responsibilities visible rather than flattening a complete workflow into an
endpoint. The [family map](refactor/CALL_PATH_SIMPLIFICATION.md) covers other
routines; [async execution](refactor/ASYNC_EXECUTION.md) explains lifespan,
choice/cancellation signals and retained synchronous Python entry points.

## Implement a small vertical slice

1. Describe inputs, decisions, effects, ordering, failure/recovery and dry-run
   behavior first. A new behavior needs its own review; existing frozen fixtures
   cannot be regenerated to bless a refactor.
2. Define small immutable request/result types and pure domain functions. Group
   cohesive values in typed models; avoid a large constructor disguised as one
   dependency parameter. A function has at most 13 parameters, normally two or
   three, at most 25 executable statements and two indentation levels.
3. Write a named application use case that calls domain functions directly and
   awaits resource methods. Keep accepted writes, membership checks, audit and
   checkpoints in their required order. Define a port only at a real external
   boundary; no port is needed for a fixed domain rule or application stage.
4. Construct concrete resources in bootstrap. Supply named stage objects when
   stages collaborate, calling their methods directly. Do not pass functions or
   bound methods for I/O, validation, presentation, time, retries or interactions.
   Required framework/standard-library call shapes need a narrow, recorded reason
   in the existing callback/boundary guard, not a general exemption.
5. Add the CLI feature and same-named `just` recipe. Use the existing `run_cli`
   boundary; do not nest event loops or create a new pooled client per call.
   If HTTP delivery is needed, colocate its declaration and endpoint in `api.py`,
   with named feature handling and a presenter. Use existing job lifecycle
   primitives for choice, cancellation and conflict behavior.
6. Give the runtime ownership of native clients and admitted work. Offload only
   complete blocking resource operations through the existing bounded boundary.
   Keep writes and dependent pagination sequential. Optimize reads only after
   demonstrating independence, result/error ordering, freshness and request cost.
7. Add tests for decision boundaries and ordered effects, partial accepted writes,
   resume, cancellation and interface translation. Use synthetic resources and
   fake HTTP, never operator files or live services. Add a focused mutation only
   when it checks a meaningful rule defect; a syntax or setup failure is not
   evidence of assertion strength.
8. Update command/configuration/state documentation where the contract changes.
   Frontend source restructuring is separate future work. A newly approved UI
   feature still needs its polling/choice/reconnect contract verified.

All new/refactored Python, including tests and tools, follows
[`AGENTS.md`](../AGENTS.md): module-scope definitions, complete annotations,
modern unions, explicit loops for complex transformations, narrow exceptions,
Google-style public docstrings and clear names. Avoid helpers that merely hide
a direct call or split cohesive logic mechanically to meet a line count.

## Verify the change

```console
uv sync --locked --dev
just ci-test
just test-final
just verify-wheel
uv run python docs/refactor/capture_baseline.py --write --output build/interfaces
uv run python docs/refactor/check_interfaces.py build/interfaces
```

Run the relevant focused recipes while developing (`test-domain`,
`test-application`, `test-spotify-async`, `test-async-execution`,
`test-read-efficiency`). The complete randomized suite checks the required
statement and branch floors independently. `test-final` checks retained callable
names and targeted policy mutations. `verify-wheel` imports the built package
outside the checkout with synthetic configuration and network access blocked.
It does not start the server or a routine.

The [CI workflow](../.github/workflows/quality.yml) repeats these contracts on
Linux and retains synthetic coverage/JUnit reports. See the
[final verification report](refactor/FINAL_VERIFICATION.md) for evidence and
limits. Then follow the approved branch → commit → PR → local preview → owner
approval → HF deployment/verification → merge → cleanup workflow in the
[roadmap](REFACTOR_ROADMAP.md#8-approved-delivery-workflow).
