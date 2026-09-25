# Item 1: compatibility and dependency baseline

**Status:** implemented and approved by the repository owner on 2026-09-24 in
the review of PR #60, subsequently deployed and merged; no application behavior
changed. [Item 2 characterization coverage](CHARACTERIZATION.md) was approved,
deployed, and merged in PR #61. [Item 3 domain policies](DOMAIN_POLICIES.md) were
deployed and merged in PR #62. [Item 4 integration ports](INTEGRATION_PORTS.md)
were deployed and merged in PR #63. [Item 5 vertical slices](VERTICAL_SLICES.md)
are implemented for review.

**Source baseline:** `37ff9f28930f22807af2f4723ebf9f13f5f9104c` on `master`.
The application code is the same as the roadmap's `fbcfc65` audit baseline.
The inventories below were captured on 2026-09-24 with the locked environment.

This is the review package for [roadmap item 1](../REFACTOR_ROADMAP.md).
It defines what later items must preserve. It does not claim to establish
complete behavioral coverage; expanded characterization tests were added in item 2.

## Review order

1. [Complete interface checklist](baseline/interfaces.md): all **44 CLI commands**,
   **115 application API routes**, **four framework routes**, and **seven web
   additions**. The latter two groups are recorded beyond the roadmap minimum.
2. [Compatibility contracts](CONTRACTS.md): defaults, interaction, dry runs,
   persistence, configuration, retries, external endpoints, and known hazards.
3. [Listening-rule and test map](RULES.md): use cases, source, existing test
   evidence, implementation-specific choices, and manual/unimplemented rules.
4. [Routine dependency inventory](baseline/routine-dependencies.md): every routine's
   internal imports, with the full package inventory in JSON.
5. [ADR-001](../adr/001-refactor-boundaries-and-async-lifetimes.md): accepted
   dependency direction, compatibility boundary, and async resource ownership.

The migration checkboxes are intentionally unchecked: they are the acceptance
checklist for future moves. Their presence does not mean registrations were
omitted from this inventory. Routes are individually enumerated rather than
inferred from a generic job-endpoint pattern; capabilities vary between jobs.

## Frozen artifacts

| Artifact | Captured contract |
| --- | --- |
| [cli-commands.json](baseline/cli-commands.json) | Every command's callback, help, parameter type, flags, argument count, requiredness, multiplicity, and defaults. |
| [cli-help.txt](baseline/cli-help.txt) | Root help plus all 44 command help pages at 100 columns with ANSI escapes removed. |
| [cli-examples.json](baseline/cli-examples.json) | Six deterministic success/validation examples, including stdout, stderr, and exit code. Application results are explicitly canned fixtures, not live data or business-rule assertions. |
| [openapi.json](baseline/openapi.json) | Full pure-API OpenAPI schema, including defaults, request/response models, operation IDs, and declared responses. |
| [web-openapi-additions.json](baseline/web-openapi-additions.json) | Four additional documented web operations and their extra component schemas. Three HTML/favicon routes are deliberately absent from OpenAPI but included in the route inventory. |
| [routes.json](baseline/routes.json) | All 126 registrations, including method sets, handlers, source locations, response models, and schema visibility. |
| [settings.json](baseline/settings.json) | All 37 Pydantic settings fields, types, requiredness, defaults, and aliases; no actual operator values. |
| [state-defaults.json](baseline/state-defaults.json) | Default values and validators for all 13 API-registered namespaces. These are empty-state defaults, not a complete grammar for active-run documents. |
| [spotify-endpoints.json](baseline/spotify-endpoints.json) | Direct HTTP calls and referenced public methods resolved against installed Spotipy 2.26.0. Includes partial-bound method references and exact source argument expressions. |
| [source-inventory.json](baseline/source-inventory.json) | Internal imports for all 74 package modules and the automation script, function call references, retry call sites, environment reads, path definitions, and URL literals. |
| [tool-versions.json](baseline/tool-versions.json) | Dependency versions that affect capture, so formatting/schema drift is distinguishable from application changes. |

Static references are evidence, not a complete dynamic call graph. Function and
line references help reviewers locate the baseline implementation and will change
when modules move. Compare interface artifacts separately from these source
location inventories during later milestones. Use
[`check_interfaces.py`](check_interfaces.py) against a separately captured
directory: it checks ten public artifacts byte-for-byte and the Spotify inventory
with only source line numbers removed. The source/dependency reports remain
historical evidence; the baseline is never regenerated to accept source moves.

## Reproduce and verify

From the repository root with the locked virtual environment installed:

```console
.venv/bin/python docs/refactor/capture_baseline.py --check
.venv/bin/python docs/refactor/capture_baseline.py --write --output /tmp/spotify-contract-review
```

`--check` recaptures and compares without rewriting the baseline. `--write`
requires an explicit choice to regenerate files; use a separate output directory
when reviewing differences. Do not approve a behavior change by blindly replacing
snapshots. The checker intentionally compares dependency versions too.

Capture runs in a temporary working directory with a replacement environment,
synthetic configuration, local state/data backends, and network/DNS calls blocked.
It disables bytecode writes during imports, replaces CLI hydration with a no-op,
does not start ASGI lifespan or jobs, and stubs business results for CLI output
examples. It never loads the operator's `.env`, OAuth caches, or library exports.
Only the requested generated artifact files are written by the capture itself.

Normalization is limited to the checkout root (`<REPO>`), ANSI stripping and
end-of-line padding removal in terminal output, fixed terminal width, and JSON
object-key ordering. Array order,
defaults, nulls, messages, CLI codes, and API operation IDs are retained. There
are no timestamp/job-ID substitutions because no jobs are executed.

## Item 1 acceptance checklist

- [x] Every command and API route is individually inventoried.
- [x] Root/command help and representative CLI output captured offline.
- [x] Pure API schemas, web additions, and hidden routes captured separately.
- [x] Routine and package dependencies recorded with source evidence.
- [x] Settings names, aliases/precedence, paths, storage formats, and namespace
  defaults recorded without private data.
- [x] Client, routine, and interface retry differences documented.
- [x] Used external HTTP/SDK operations recorded from source and installed code.
- [x] Implemented listening rules mapped to use cases and existing tests;
  manual/unimplemented rules and observed discrepancies distinguished.
- [x] Accepted ADR documents boundaries, alternatives, async ownership, and
  compatibility implications.

## Verification for this item

- Randomized existing suite: **1,127 passed**, **90.22% statement coverage**.
  The existing Starlette/TestClient dependency deprecation warning remains.
- Ruff lint/format and mypy pass for the application and the capture script.
- All 13 baseline artifacts reproduce; a deliberately altered OpenAPI snapshot
  is rejected by `--check` in a separate temporary output directory.
- All 110 relative documentation file links and 63 named test references resolve.
- The 115 application route registrations match the 115 captured OpenAPI
  operations; 44 unique commands have 45 help captures including root help.

The user-approved Git workflow still applies. Item 1 completed deployment,
merge, and branch cleanup before item 2 began. Every later item requires its own
PR approval before deployment and merge.
