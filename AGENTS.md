## Imported Claude Cowork project instructions

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
