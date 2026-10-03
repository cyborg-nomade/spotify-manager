# ADR-003: direct paths from feature adapters to business use cases

**Status:** Accepted direction; implementation pending in Item 7a.

**Date:** 2026-10-03

**Decider:** repository owner, approving the simplification recommendation during
Item 7 review. This decision does not approve deployment or merge of PR #66.

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

Insert a dedicated synchronous simplification Item 7a after the Item 7 release
and before native async transport. Keep ADR-001's dependency direction and
ADR-002's job behavior. Refine their implementation with these rules:

- A feature adapter calls a named application use case with explicit dependencies.
  Its result returns to an interface presenter. Business stages may call other
  cohesive, public application functions when they have distinct responsibilities.
- Bootstrap constructs dependencies at startup or the appropriate invocation
  boundary. Separate construction from business execution and response rendering.
  Do not move invocation-specific observations or callback binding to startup.
- Retain required public compatibility facades as entry points. After entering a
  feature adapter, ordinary execution should not return through an API/CLI facade
  or a legacy routine/processor wrapper to reach the use case.
- Default infrastructure implementations use their actual implementations, rather
  than locating callbacks or constants through a legacy facade. Keep supported
  overrides explicit at the external boundary. Document any narrow exception that
  cannot yet be removed without changing a frozen contract.
- Retain stateful contexts where they own job signals, callbacks or resources.
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
- Resource scopes, clock reads, configuration reads and callback ownership must
  retain their existing observation and cleanup order.
- The frontend receives no source reorganization in this milestone. Its separate
  refactor will need its own scope, tests and approval.

## Action items

1. [x] Record the owner-approved direction and insert Item 7a in the roadmap.
2. [ ] Release approved Item 7, then start Item 7a from clean, current `master`.
3. [ ] Inventory the runtime and compatibility paths for every routine family.
4. [ ] Simplify album evaluation and Sauvignon, then the remaining families.
5. [ ] Verify contracts/effects, typing, boundaries, coverage and local web behavior.
6. [ ] Open the dedicated Item 7a PR and await approval before deployment/merge.
7. [ ] Carry the call-path acceptance criteria through Items 8–12.
