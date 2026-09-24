# Item 2: offline characterization and fault injection

**Status:** implemented for review. Application code, dependencies, and public
contracts are unchanged. Deployment and merge await approval of this item's PR.

The oracle is the unmodified application at `309ad9660e1e23ed11e08a45125175a987fda182`.
Item 1's [interface baseline](README.md) remains frozen. This item adds workflow
observations that later policy extractions and use cases must also preserve.

The [project coding fundamentals](../../AGENTS.md) apply to this harness too.
Named module-level helpers replace closures; function signatures are typed,
docstrings describe the public helpers, and scenario setup stays explicit.

## What is covered

There are **129 committed traces across 12 scenarios**: 12 ordinary runs, nine
supported previews, and 108 failure/re-entry runs. The preview for upload is the
existing preparation step, before calling the publishing function. Album
assessment, interactive album review, and live analysis do not expose a dry-run
parameter, so this suite does not invent one.

| Migration family | New executable scenarios | Boundaries observed |
| --- | --- | --- |
| Foundation / first vertical slice | `album`, `review`, `requeue` | Three-track keep threshold, live reads, artist following, explicit removal prompt, album mirror and statistics writes, removal audit, replacement-before-removal, and re-entry after either remote write. |
| Release progression | `slow`, `wine`, `kids` | Pending plans, add/remove ordering, audits, and checkpoints before planning, after planning, after mutation, and around completion. |
| History and discovery | `history`, `queue`, `release` | Last.fm merge and backup, canonical export replacement, queue transitions, release discovery, persisted artist mappings, and the history refresh requested by a release-check preview. |
| Deep listening and retrospectives | `palace` | Fixed Random.org indexes and timestamp, live album refresh, ten-track batch, alphabetical cursor, audit, and re-entry against updated playlist contents. |
| Library and legacy | `analysis`; existing legacy processor tests now use synthetic inputs | Multiple live track pages, staging/checkpoint state, final mirror writes, audit records, and re-entry after a failed second-page read or publication. |
| Operational integration | `upload`; independent HTTP-contract tests | Exact Hub operation paths and content hashes, failure before/after commit acceptance, Spotify request bodies, pagination URLs, decoding, retry budgets, and error headers. |

The [scenario factories](../../tests/characterization/scenarios.py) reuse the
existing mutable routine fakes. The Palace fake is extended to expose accepted
playlist additions on subsequent reads. The [trace harness](../../tests/support/effects.py)
wraps their effects; it does not replace routine decisions. Golden files are in
[tests/characterization/fixtures](../../tests/characterization/fixtures).

Existing tests remain part of the acceptance gate. In particular, the routine
suites retain New Year saved-plan recovery, Queue 2 postfill recovery, Queue 3
annual-import idempotency, composer progression, discovery filtering, user
choices, and cancellation. State and library-data suites retain compare-and-swap
conflicts, corrupted payloads, backups, and publication failures. The new shared
scenarios are representatives of each family, not a claim that every routine's
every branch now has a golden trace. Before moving another routine, extend its
scenario with any unrepresented decisions or effects from the
[listening-rule map](RULES.md). Items 5–9 must compare extracted and legacy
implementations through these same fixtures; there is no extracted implementation
to compare yet in item 2.

## Trace and failure semantics

Every watched operation records its arguments before execution and its returned
value after acceptance. Observations are copied at recording time so later
mutation cannot rewrite earlier checkpoints. One-shot faults can target a named
operation's first or later occurrence:

- **Before acceptance:** the fake or persistence function has not executed.
- **After acceptance:** its state change has happened, but the caller receives an
  error instead of an acknowledgement.

The fault tests capture the first outcome and all resulting files/remote state,
clear the process-local state and data service caches, and invoke the routine
again against the retained files and simulated server. This tests re-entry after
an exception, not an OS kill in the middle of an individual file write. Existing
atomic-storage tests cover lower-level write failures. Injected workflow errors
are `EffectInterruptedError`; separate real-client tests exercise transport
`Timeout`, HTTP errors, and their actual retry policies.

The recorder catches only injected interruptions, library-sync/upload errors,
`OSError`, and `SpotifyException`. Unexpected programming errors propagate and
fail the test immediately; dedicated harness tests verify this distinction.

Clocks and run IDs are fixed, as are catalog IDs, scrobbles, random selections,
and choices. Traces preserve result fields, prompt arguments/answers, echo
messages, ordered mutations, checkpoints, mirrors, audit records, and final
artifact contents. JSON is compared structurally without deleting timestamps,
IDs, nulls, or ordered lists. Temporary checkout paths become `<TMP>`, callback
identities become `<callback>`, sets are sorted, and gzip backups are compared as
decoded JSON. Upload operations retain SHA-256 content hashes. Incidental JSON
whitespace and gzip headers are not golden contracts; the existing serialization
and integrity tests remain responsible for those representations.

Two observed recovery limitations are deliberately retained:

- Requeue has no durable pending plan. After the old marker is successfully
  removed but acknowledgement is lost, the next invocation operates on the new
  head. In this fixture it drops the last eligible release. It is not equivalent
  to the recovery path where adding succeeded and removal never happened.
- Album review can repeat an accepted Spotify removal if saving the local album
  mirror failed. A Hub upload can likewise repeat its commit after losing the
  acknowledgement. The traces expose this behavior without silently adding new
  idempotency guarantees.

Dry runs also differ: Slow Listening writes its audit; release checking invokes
history refresh with `dry_run=False` and persists artist mappings. Requeue writes
neither mutations nor audit during its preview. These distinctions are recorded,
not normalized away.

## Isolation and independent adapter tests

[test configuration](../../tests/conftest.py) installs synthetic settings before
collecting application tests and disables reading the operator's `.env`. Local
state/data backends and temporary working directories are automatic. Existing
Path constants, nested path maps/dataclasses, and already-bound path defaults are
redirected, including imported aliases. The album-track cache remains in memory.

Socket connections, DNS resolution, and UDP sends are blocked. A process-level
audit guard also rejects opening, removing, renaming, or creating files at the
operator's project data/auth paths, even when a default or monkeypatch misses the
redirection. Directory enumeration is permitted for coverage discovery. These
are test-process guards, not an OS sandbox for arbitrary child processes. The
[harness tests](../../tests/characterization/test_harness.py) check the guards,
strict response scripts, copied observations, and before/after fault semantics.

Six existing tests were relying on operator exports (five control/statistics
checks and one CLI publication check); they now construct deterministic inputs
and assert exact results. Other job tests previously inherited a local Last.fm
key; collection now supplies synthetic credentials instead.

[HTTP contracts](../../tests/client/test_spotify_http_contracts.py) run the real
`RotatingSpotify` and Spotipy decoder against scripted `requests.Response`
objects. They do not import domain fakes. They freeze pagination, malformed
responses, canonical `/items` writes, HTTP status/reason/`Retry-After`, and the
four-attempt GET timeout budget; ambiguous POST/PUT/DELETE timeouts are not
retried by the transport. No network requests or real sleeps occur.

## Run and review

The ordinary full-suite command includes all new tests:

```console
.venv/bin/pytest --random-order --random-order-bucket=global --cov=spotify_manager tests
.venv/bin/pytest tests/characterization tests/client/test_spotify_http_contracts.py
.venv/bin/python docs/refactor/capture_baseline.py --check
```

Golden tests never update their expected output automatically. To inspect a
candidate capture, write to a separate directory:

```console
.venv/bin/pytest tests/characterization/test_routine_traces.py --characterization-output /tmp/spotify-characterization-candidate
```

Review changes against the committed fixtures, especially effects preceding the
`process/restart` event and final artifacts. Each JSON line represents one event;
`python -m json.tool <fixture>` expands it for inspection. The capture command
rejects destinations inside the golden-fixture directory. Do not replace a
fixture merely to make a migrated implementation pass. Add the new implementation
as a scenario adapter and compare its observations with the same frozen oracle.

[Regression-sensitivity tests](../../tests/characterization/test_regression_sensitivity.py)
prove that the parity assertion rejects four deliberate changes: ceil instead of
floor, removal before replacement, a missing audit, and writes during a dry run.
The patch is scoped to each test; production source is never rewritten.

## Verification

- **1,309 tests passed** with global randomized ordering and seed `20260924`;
  a second run with seed `20260925` passed while measuring branches.
- **90.38% statements** (16,424 / 18,173), up from 90.22%.
- **74.84% branches** (3,826 / 5,112), up from 74.43%.
- All 129 traces replay unchanged; all 13 item 1 interface artifacts reproduce.
- Ruff lint/format passes for application, baseline tooling, and changed tests;
  mypy passes for application, baseline tooling, and all Python files added or
  changed in this item (89 files in total).
- The existing Starlette/TestClient deprecation warning remains.

The diagnostic branch run uses `--cov-branch --cov-fail-under=0` to measure
branches separately from the existing statement-only gate; it does not change
project coverage configuration. The final 95% statement / 90% branch goals are
still pending later migrations. This item establishes reproducible behavior and
fault evidence while maintaining the approved statement baseline.
