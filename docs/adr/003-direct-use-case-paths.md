# ADR-003: direct paths from feature adapters to business use cases

**Status:** Accepted; Item 7a was approved, deployed and merged in PR #67 on
2026-10-26.

**Date:** 2026-10-03

**Decider:** repository owner, approving the simplification recommendation during
Item 7 review. Item 7 PR #66 was subsequently approved, deployed and merged; this decision does not approve the Item 7a release.

## Context

Items 3–7 separated policies, application use cases, infrastructure and feature
delivery. The owner identified that following a frontend request still requires
too many forwarding layers. Album evaluation, for example, passes from the API
facade through a feature handler, a legacy processor and a bootstrap execution
helper before reaching `application.album_review.review_album`.

Some composition modules also read routine-module globals to preserve old test
substitutions. This can send execution back through legacy modules and obscure
which dependency the business use case actually needs. These compatibility
paths helped make migration reviewable, but should not become the permanent
internal architecture. Async conversion would otherwise carry them into more
complicated resource and task ownership.

Preserve the approved behavior contracts, public imports, framework metadata,
supported dependency overrides, credential behavior and accepted effect order.
Keep the application a modular monolith. Frontend source restructuring remains
a future targeted refactor; its current integration contracts still apply.

## Decision

The owner's reviews through 2026-10-23 extend this rule across the codebase.
Fixed domain rules are imported and called directly. Application stages call
named stages, while external resources expose cohesive methods. Constructors
and calls receive resource owners rather than their functions or bound methods.
This applies to I/O, serialization, schemas, presenters, checkpoints, operator
choices, notifications, retries, cancellation, clocks, randomness and waits.
A runtime, interaction or compatibility label is not an exemption.

Compatibility entries accept named schemas and resources too. Retain function
arguments only where an external framework or standard-library API requires
them: route/dependency registration, thread targets, default factories, ordering
keys and the JSON encoder's fallback. Two private concrete SDK captures retain
observable binding time: the offset-page endpoint and the event setter used
for restoration. The dependency guard records those exact fields and reasons;
its separate call-site scan also rejects hidden function-valued arguments.

Retry attempt scopes leave the actual request directly visible in its caller.
The policy owns entry, failure classification, bounded waits and acceptance;
it does not receive or execute a supplied operation. Keep original cancellation,
retry counters, errors, accepted effects and cleanup order. Integration adapters
must not execute hidden application stages. Tests retain their original results,
ordered-effect recordings and frozen fixtures while changing boundary wiring.
This extends Item 7a and does not approve its deployment or merge.

The owner's 2026-10-05 review tightens this decision before any async work:
route declarations must sit beside their endpoint functions, and the normal
path through named application functions, domain rules and presenters must be
navigable with editor definition lookup. Move runtime administration and
compatibility exports out of the route module. Functions have an absolute
maximum of 13 parameters, usually two or three; group cohesive data and
resources in typed models. Do not disguise a large dependency list in a
generated constructor. Client construction belongs to concrete client wiring,
not routine modules. Python call sites may change to meet this signature rule;
HTTP/CLI contracts and ordered business effects remain frozen.

Insert a dedicated synchronous simplification Item 7a after the Item 7 release
and before native async transport. Keep ADR-001's dependency direction and
ADR-002's job behavior. Refine their implementation with these rules:

- A feature adapter calls a named application use case with explicit dependencies.
  Its result returns to an interface presenter. Business stages may call other
  cohesive, public application functions when they have distinct responsibilities.
- Bootstrap constructs dependencies at startup or the appropriate invocation
  boundary. Separate construction from business execution and response rendering.
  Do not move invocation-specific observations or observer binding to startup.
- Retain required public compatibility facades as entry points. After entering a
  feature adapter, ordinary execution should not return through an API/CLI facade
  or a legacy routine/processor wrapper to reach the use case.
- Default infrastructure implementations use their actual implementations, rather
  than locating callbacks or constants through a legacy facade. Keep supported
  overrides explicit at the external boundary. Document any narrow exception that
  cannot yet be removed without changing a frozen contract.
- Retain stateful contexts where they own job signals, interactions or resources.
  Remove forwarding-only contexts and wrappers when plain functions are clearer.
  Do not add a service locator, workflow framework or one new service per helper.
- Review the complete input and return path by family. Each retained wrapper must
  have a distinct purpose; there is no arbitrary call-depth or file-count target.

The [implementation plan](../refactor/CALL_PATH_SIMPLIFICATION.md) defines the
representative paths, migration order and verification evidence.

## Options considered

| Option | Complexity and cost | Benefits | Limitations |
| --- | --- | --- | --- |
| Leave simplification until Item 12 | Small immediate cost; harder after async migration | Keeps the original sequence | Async lifetime work inherits avoidable detours; readability remains unresolved. |
| Simplify synchronously before Item 8 | Bounded structural work across existing families | Existing fixtures isolate wiring changes; async starts from clearer ownership | Adds a milestone and requires careful preservation of overrides and observation timing. |
| Replace the architecture wholesale | High cost and broad simultaneous change | Freedom to redesign every layer | Discards useful policies/tests and increases behavior risk without a demonstrated need. |

Choose the dedicated synchronous step. No technology or deployment model changes.

## Trade-off analysis

Preserving a public import does not require making it an internal dependency.
Keep external wrappers and test them as contracts, while testing application
behavior through explicit ports and interface behavior through supplied use
cases. Do not weaken existing assertions merely to eliminate a patch seam.

Some additional code remains justified: HTTP and CLI validation differ, jobs own
mutable signals, and infrastructure parses external payloads. Simplification
removes unnecessary forwarding; it does not merge these responsibilities or
move transport/presentation into the business rules.

## Consequences

- Requests become easier to follow from input to policy and back to output.
- Async work can change transport and lifetime without also untangling facade
  dependencies. The simplification itself keeps synchronous execution.
- Tests that rely on legacy internals may need equivalent direct-boundary
  coverage before their internal patch targets migrate. Public contract tests
  and frozen fixtures remain unchanged.
- Resource scopes, clock reads, configuration reads and observer ownership must
  retain their existing observation and cleanup order.
- The frontend receives no source reorganization in this milestone. Its separate
  refactor will need its own scope, tests and approval.

## Action items

1. [x] Record the owner-approved direction and insert Item 7a in the roadmap.
2. [x] Release approved Item 7, then start Item 7a from clean, current `master`.
3. [x] Inventory the runtime and compatibility paths for every routine family.
4. [x] Simplify album evaluation and Sauvignon, then the remaining families.
5. [x] Verify contracts/effects, typing, boundaries, coverage and local web behavior.
6. [x] Review, approve, deploy and merge Item 7a PR #67 (2026-10-26).
7. [ ] Carry the call-path acceptance criteria through Items 8–12.


## Owner clarification, 2026-10-23: function arguments

Named operator interactions, notifications, clocks, cancellation, randomness,
waiting and retries replace function-shaped dependencies too. A callback's role
alone does not justify it. Readability takes precedence over convenience and
configurability; use direct named calls or cohesive objects with explicit methods
whenever they can preserve the same behavior. Compatibility APIs receive named
schemas and resources rather than retaining unnecessary function arguments.

Function arguments remain appropriate only where an external framework or a
standard-library API actually requires them, such as registered routes, thread
targets, dataclass default factories and sorting keys. The dependency guard permits
only two private SDK method captures: the selected library page endpoint and the
optional event setter restored after a job. They preserve the original lookup
and binding time; they are not supplied business execution dependencies.

Retry attempt scopes keep the concrete operation visible at its call site. Each
scope preserves the original failure classification, attempt count, wait,
cancellation and accepted-result boundary. Python wiring and test doubles may
change; frozen HTTP/CLI results, SDK calls, errors and ordered effects do not.

This clarification was implemented and verified in Item 7a PR #67. The owner
approved it on 2026-10-26; the Space deployment and merge were verified before
Item 8 began. The [verification guide](../refactor/CALL_PATH_SIMPLIFICATION.md)
records its final evidence. These call-path rules continue through later items.
