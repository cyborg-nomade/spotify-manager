## Imported Claude Cowork project instructions

## Python engineering fundamentals

Readability and maintainability are the highest priorities. Act as a Principal
Python Engineer: write idiomatic, straightforward code that another programmer
can easily inspect, debug, and change. These rules apply to new and refactored
Python, including tests and tooling:

1. Define functions and classes at module scope. Ordinary class methods are
   allowed; do not define local functions, closures, or inner classes. Keep
   indentation within a function to at most two levels, using guard clauses and
   early returns for errors and boundary conditions.
2. Keep functions under 20–25 executable lines and cyclomatic complexity low.
   Prefer explicit, simple code over clever abstractions. Do not use compound or
   multiline comprehensions; use an explicit loop or a small, named helper.
3. Give every function and method complete parameter and return annotations.
   Use modern built-in collections and `T | None`; avoid `Any` unless the external
   boundary genuinely requires it. The project remains on its configured Python
   version; this is not a request to downgrade it.
4. Give public functions, methods, and classes Google-style docstrings describing
   intent, `Args:`, `Returns:`, and `Raises:` where applicable. Trivial private
   helpers may omit docstrings when their names and types fully explain them.
5. Follow PEP 8 and Ruff formatting. Catch specific exception types; do not add
   catch-all `except Exception:` blocks.

Apply these rules throughout the approved incremental refactor, preserving the
frozen behavior contracts. Existing legacy code is brought into compliance as
its roadmap item is handled; do not mix unrelated production rewrites into a
test-only item. Keep helpers cohesive rather than splitting code mechanically
or introducing a framework merely to satisfy a line limit.

## Approved refactor workflow

Follow the approved roadmap in `docs/REFACTOR_ROADMAP.md`. For each roadmap item:

1. Start from a clean, up-to-date `master` and create a dedicated branch.
2. Implement and verify the item, then commit the changes.
3. Open a GitHub pull request for user review.
4. Wait for the user's approval before deploying or merging.
5. After approval, deploy the changes to Hugging Face, verify the deployment,
   then merge the pull request.
6. Clean up the item's branch and any temporary worktree, return to a clean,
   up-to-date `master`, and only then proceed to the next item. Preserve unrelated
   user files and changes during cleanup.

The roadmap was approved on 2026-09-24. The user explicitly authorized opening
and merging the preparatory documentation PR. After that PR is merged, return
to a clean `master`, notify the user, and wait for their instruction before
starting item 1. This preparatory authorization does not approve later item PRs.
