# Item 11: strict typing and architecture enforcement

**Status:** implemented for review on `codex/refactor-11-type-architecture-gates`,
based on Item 10 merge `3cb2f78`. Deployment and merge await this item's approval.

## Default typing protects the business rules

The default package mypy command now applies strict checking to every domain and
application module. It also rejects explicit `Any` and types inherited from
untyped imports in these layers. Collections must be parameterized, signatures
complete and returns precise. Redundant casts are checked package-wide; six
unnecessary casts were removed without changing their values.

Global missing-import suppression is disabled. The only retained missing-type
exceptions are `spotipy.*` and `pyuca.*`, installed libraries without published
type information. Concrete SDK, transport, JSON and collation adapters own those
external boundaries. There are no new source-level type ignores, casts to `Any`,
or suppressed application errors.

The Spotify client contract returns `object` instead of `Any`. The routine-state
ports exchange `dict[str, object]`, retaining unknown versioned fields. Their
callers must narrow values before operating on them. Concrete native transport
continues to return the existing recursive `SpotifyJson` type; named music ports
continue to exchange typed domain facts rather than raw endpoint dictionaries.

[`spotify_payloads.py`](../../spotify_manager/infrastructure/spotify_payloads.py)
names the few raw artist-credit and created-playlist fields still consumed at
legacy SDK edges. These `TypedDict` annotations add no runtime validation,
coercion, copying or field filtering. Narrow membership annotations retain even
malformed truthy values and the original empty/null/indexing failures. One state
handoff widens an already known decision mapping's value type while retaining
the original mapping identity. Endpoint parsers, schema validators and native
failure ownership remain unchanged.

Existing retry scopes keep operations and their typed results at the direct
call site. Resource ownership remains in the invocation/lifespan context managers
introduced in Item 9. This item adds no callback dependencies, retry behavior,
resource lifetime or execution layer.

## Architecture and readability checks

The new [architecture suite](../../tests/architecture/) supplements the existing
domain/application isolation, direct-call, callback and fresh-process import
guards:

- Resolve absolute, relative, aliased, deferred and type-only imports before
  checking dependency direction. Application code can import its own ports,
  domain rules and the existing explicit value/schema utilities; UI, bootstrap,
  infrastructure, settings, runtime services and SDKs remain outside.
- Reject cycles within the domain and application feature graphs, including
  type-only edges. This is a static source graph, complemented by the existing
  fresh-process startup tests.
- Reject direct or aliased access to another routine's private helpers. Public
  compatibility edges remain supported; the direct-dependency guards continue
  to prohibit internal execution through forwarding facades.
- Reject local functions/classes, compound or multiline comprehensions and
  signatures over 13 parameters throughout production source, including
  variadic parameters. Domain/application functions also have a 25-statement
  ceiling and at most two indentation levels. Ordinary methods and flat `elif`
  chains are allowed.
- Run real default-config mypy probes against deliberately invalid business
  modules. Tests prove that untyped definitions, bare collections, explicit
  `Any` and missing SDK types fail without an optional `--strict` argument.

The remaining multiline comprehensions were replaced with explicit loops or
ordinary action counts. These changes retain encounter order, short-circuit
validation, error translation, result categories and accepted effect order.
Stale business docstrings now describe named interaction/progress resources.

## Independent coverage floors

[`coverage_gate.py`](../../tests/architecture/coverage_gate.py) reads the original
coverage.py JSON counters and checks each metric independently:

| Scope | Statement minimum | Branch minimum |
| --- | --- | --- |
| Entire package | 95% | 90% |
| Domain | 98% | 95% |
| Application | 98% | 95% |

A high combined percentage cannot conceal a failing metric or business layer.
The gate requires branch instrumentation and the exact current Python source
inventory: omitted modules and stale deleted modules both fail. It compares
integer counters before rounding. Existing coverage exclusions are unchanged.
Negative tests exercise deficient metrics, missing instrumentation, absent
modules, stale reports, exact thresholds and the command's failing exit status.

## Local and GitHub checks

```console
uv sync --locked --dev
just lint-mypy
just lint-inner
just test-architecture
just ci-test
```

`just ci-test` runs lint, package/automation typing, strict inner/native typing and
the complete randomized suite with branch instrumentation. It then enforces the
independent floors. `PYTEST_REPORT_PATH` still overrides the JUnit report;
`COVERAGE_REPORT_PATH` overrides `build/reports/coverage.json`.

The [Backend quality workflow](../../.github/workflows/quality.yml) runs on PRs
to master, pushes to master and manual dispatch. It exposes two checks:

1. **Typing and architecture:** formatting, package/automation mypy, strict
   business/native typing, architecture/direct-call tests and all frozen public
   interface artifacts.
2. **Tests and independent coverage floors:** the full randomized offline suite
   and the separate statement/branch gates. Synthetic JUnit and coverage reports
   are retained for 14 days, including on failure.

Both jobs use Python 3.14 and locked development dependencies, read-only repository
permissions and no service secrets. Action revisions and the uv version are
pinned. The existing nightly production automation is unchanged. Repository
branch-protection settings are unchanged.

Configuration follows the official [mypy configuration reference](https://mypy.readthedocs.io/en/stable/config_file.html),
[uv Actions guidance](https://docs.astral.sh/uv/guides/integration/github/) and
[GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
The strict flags are explicit per module; focused checks also run `--strict`.

## Verification and review

Final local verification on 2026-10-30:

- **11,117 tests passed**, randomized seed `20261030`, in 407.83 seconds.
  The existing Starlette TestClient dependency deprecation is the only warning.
- Package: **95.69% statements** (36,536 / 38,181), **92.17% branches**
  (5,825 / 6,320), **95.19% combined**. All independent coverage gates pass;
  the existing **933 excluded lines** are unchanged.
- Domain: **2,560 statements / 886 branches, 100% each**.
- Application: **8,782 statements / 2,068 branches, 100% each**.
- All **68 new architecture/typing/payload/coverage guard tests** pass as part
  of the complete suite. Invalid-source probes prove the guards reject failures.
- Package/automation mypy passes **687 files**; strict business/native/test typing
  passes **431 files**. Ruff and formatting pass **696 source/guard files**.
  The **136 changed/new functions** pass the structural audit.
- All **11 frozen public artifacts** match without new normalizations. Original
  expected fixtures, frontend source and callback exemptions are unchanged.
- Locked installation, source distribution and wheel build pass; the new boundary
  schemas are included in the wheel. All **114 relative links** in changed guides
  resolve.
- Local read-only health, password, shared-state/source and all **20 reconnect**
  checks pass with no active jobs. The four restored operator files retain their
  exact backed-up bytes and are excluded from the PR.

GitHub repeats these checks on Linux and retains the synthetic reports on the PR.
Tests use synthetic configuration, block live sockets and protect operator files.

The local web preview for this branch is **http://127.0.0.1:8766/**, with any
nonempty local unlock text. Its startup, password gate, shared-state/source reads
and all 20 reconnect endpoints are checked without starting a routine. The latest
four operator files are backed up separately, restored after startup hydration
and excluded from the PR.

Item 12 next completes the final compatibility and documentation audit. Frontend
source restructuring remains a future targeted refactor.
