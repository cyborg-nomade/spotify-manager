# Routine improvements roadmap

**Approved:** 2026-11-03. The owner approved the proposed roadmap and authorized
starting implementation. Deployment and merge require approval of each item's
pull request. The completed [refactor roadmap](REFACTOR_ROADMAP.md) remains closed.

## Engineering and release rules

Follow [AGENTS.md](../AGENTS.md), the [architecture](ARCHITECTURE.md), and
[ADR 003](adr/003-direct-use-case-paths.md). Keep the modular monolith, native
async execution, named application stages, pure domain decisions, explicit typed
resources, and bootstrap-owned construction. Do not add function-shaped execution
dependencies or a workflow framework. Python readability, typing, function-size,
docstring, and exception-handling requirements apply to tests and tooling too.

Each item starts from clean, up-to-date `master` on its own `codex/…` branch:

1. Implement the item and its focused behavioral and recovery checks.
2. Run the applicable existing lint, typing, architecture, coverage, interface,
   and packaging gates. Document intended changes to previously frozen behavior.
3. Commit and open a PR. Launch the local web environment on that branch and
   provide its URL, verification evidence, and operator testing instructions.
4. Wait for the owner's explicit PR approval before deployment or merge.
5. Deploy the approved changes to Hugging Face without overwriting unrelated
   state or data, verify the deployment, then merge the PR.
6. Verify merged workflow changes where applicable. Clean up the item branch
   and temporary worktrees, preserving unrelated files and operator changes.
   Return to clean, current `master` before starting the next item.

Interactive changes need browser verification of choices, cancellation,
reconnection after reload, and relevant mobile layouts. State changes need
migration and interruption/restart evidence. Update contract fixtures only for
the behavior deliberately changed by the item. Each PR records its scope,
validation, state implications, rollback procedure, and outstanding release checks.

## Item 1: restore reliable artist synchronization

**Status:** implemented, approved, deployed, and verified in Recent and Full modes.
Full verification exposed repeated Spotify cooldowns. The owner requested
automatic retries on 2026-11-03 and approved the extension. It is deployed at
Space revision `7137ec9b36a5e532ed24073bdcfc3a939b4098d2`.
The owner's Full run completed successfully and its durable publication was
verified: 37,851 unique artists at `2026-11-03T14:07:51.246431Z`.
Release: [PR #73](https://github.com/cyborg-nomade/spotify-manager/pull/73).

The [investigation and review guide](improvements/01_ARTIST_SYNC.md) records the
confirmed packaged Git LFS pointer, recovery boundary, verification, and rollout.

Reproduce the deployed `YourLibrary.json` read failure. Trace recent refreshes,
full cursor scanning, fallback activation, export loading, checkpoints, and durable
publication. Establish the failure history and source-export packaging behavior.
Fix the cause while preserving the complete available candidate set and the last
valid mirror on failure. An incomplete refresh must not become a successful
publication. Distinguish completed refreshes from maintenance-window pauses.
During Spotify rate limits, wait for the reported cooldown and retry the same
request automatically, including repeated limits. Keep waiting jobs cancellable
and respect scheduled maintenance deadlines.

**Acceptance:** recent and full modes produce validated output and retain durable
publication. Regression checks cover the observed failure, incomplete upstream
responses, and interrupted recovery. Production recovery is verified after PR
approval and deployment; development checks use isolated data and state.

## Item 2: align the signal board and nightly refresh modes

**Status:** implemented, verified, and owner-approved;
release record: [PR #74](https://github.com/cyborg-nomade/spotify-manager/pull/74).
Details: [implementation and release guide](improvements/02_SIGNAL_BOARD_SYNC.md).

Give Last.fm the same Recent / Full controls as the Spotify files. Remove its
dry-run checkbox from the board while retaining useful CLI/API preview support.
Recent performs incremental history synchronization; Full rebuilds history.
Use recent Last.fm sync on incremental scheduled runs and full sync on weekly
full runs. Preserve Berlin calendar handling, maintenance deadlines, resumability,
and duplicate-trigger protection. New Year's explicit history rebuild remains.

**Acceptance:** UI requests, API parameters, and automation agree on modes.
Calendar-boundary tests cover the schedule. An unchanged artifact is distinct
from a failed or never-completed refresh. Verify Actions after merge.

## Item 3: improve the Blast from the Past panel layout

**Status:** implemented, verified, and owner-approved;
release record: [PR #75](https://github.com/cyborg-nomade/spotify-manager/pull/75).
Details: [implementation and review guide](improvements/03_BLAST_PANEL_LAYOUT.md).

Put Count/Cap and its input on the first row, Dry run / Run / cancellation on a
middle row, and the existing Artists controls and progress below. Keep the change
focused on HTML/CSS and preserve current action and element bindings.

**Acceptance:** desktop and narrow mobile layouts have no horizontal overflow,
with readable controls and sensible keyboard order.

## Item 4: add manual matching to Blast and Daily Mind Radio

**Status:** implemented, owner-approved and deployed on 2026-11-04 in
[PR #76](https://github.com/cyborg-nomade/spotify-manager/pull/76). The
[review guide](improvements/04_MANUAL_TRACK_MATCHING.md) records behavior,
interaction contracts, isolated previews and verified release checks.

Keep existing automatic matching policies. When no good automatic match exists,
use a named application stage to search the available artist, track, and album
text. Present up to ten Spotify results in search order with track, artist
credits, album, and Spotify link. Do not discard manual candidates because they
fail automatic similarity thresholds. Offer selection, explicit no match, and
cancellation in web and CLI. Preserve routine-specific eligibility, duplicate,
playlist-order, cancellation, and dry-run rules.

**Acceptance:** cover automatic success, ambiguity, fewer than ten results, empty
results, manual selection, rejection, cancellation, and preview execution.

## Item 5: extend matching and repair New Year's unresolved-item handling

**Status:** implemented, owner-approved, deployed and verified on 2026-11-04 in
[PR #77](https://github.com/cyborg-nomade/spotify-manager/pull/77). The
[implementation and review guide](improvements/05_LASTFM_MATCHING.md) records
the consumer inventory, Chevelle diagnosis, interaction protocol and release rules.

Inventory remaining Last.fm track/album consumers, including Found Art,
Something Old, and Sauvignon. Integrate the shared fallback where applicable;
album resolution presents album candidates. New Year's unresolved entries offer
selection/drop instead of aborting. Carry explicit dropped outcomes through
planning, charts, and playlist application.

Investigate Chevelle's `In Debt to Earth` / `In Debt to the Earth` using actual
Spotify responses, and preserve a regression fixture without a song-specific rule.

**Acceptance:** the reported case can be resolved manually; dropping one item
does not abort the remaining plan. Dry run creates a complete preview without
applying playlist changes.

## Item 6: skip proposed next albums in Slow Listening

**Status:** implemented, owner-approved, deployed and verified on 2026-11-04 in
[PR #78](https://github.com/cyborg-nomade/spotify-manager/pull/78). The
[implementation and review guide](improvements/06_SLOW_LISTENING_ALBUM_SKIPS.md)
records the interaction, recovery contract and isolated review environments.

At album transitions, offer accept, skip whole proposed album, and pause.
Repeated skips propose successive albums until acceptance or exhaustion.
Preserve within-album progression and release-date tie ordering.

**Owner clarification:** this does not add an action to abandon the current album.

**Acceptance:** multiple skips, exhaustion, pause/resume, and dry-run results work
without requiring track-by-track rejection of an entire album.

## Item 7: confirm the next album in Requeue for a Dream

**Status:** implemented, owner-approved, deployed and verified on 2026-11-04 in
[PR #79](https://github.com/cyborg-nomade/spotify-manager/pull/79). The
[implementation and review guide](improvements/07_REQUEUE_ALBUM_CONFIRMATION.md)
records successor selection, freshness checks and isolated review environments.

Present each next eligible album before applying a transition. Accept selects it;
Skip proposes its successor; Cancel leaves the current marker unchanged. Clearly
present exhaustion and retain the current completion policy. Recheck the live
playlist head after interaction and before mutation.

**Acceptance:** acceptance, repeated skips, exhaustion, cancellation, and a playlist
changed during the prompt have explicit tested outcomes.

## Item 8: show previous Something Old choices

**Status:** implemented, owner-approved, deployed and verified on 2026-11-05 in
[PR #80](https://github.com/cyborg-nomade/spotify-manager/pull/80). The
[implementation and review guide](improvements/08_SOMETHING_OLD_CHOICE_HISTORY.md)
records stable artist identities, accepted-effect recovery and isolated previews.

Record successful applied selections by stable artist identity, mode, and date.
Show prior modes and the most recent choice beside the three selection options
in web and CLI. Recover available audit history with provenance. Previews and
abandoned selections do not count as completed choices. Keep the current mode an
explicit operator decision.

**Acceptance:** history survives restart and deployment, remains attached to the
correct artist, and has tested recovery after accepted effects.

## Item 9: order New Wine replacements and confirm cellar transfers

**Status:** implemented, owner-approved, deployed and verified on 2026-11-05 in
[PR #81](https://github.com/cyborg-nomade/spotify-manager/pull/81). The
[implementation and review guide](improvements/09_NEW_WINE_ORDER_AND_TRANSFERS.md)
records deferred execution, durable skips and isolated review environments.

Apply continuations within existing records before appending selections that
begin new records, preserving encounter order within each group. For A finishing,
B advancing, and C finishing, the result is B's next track, A's new record, C's
new record. Persist execution progress so restart retains the desired order and
replacement-before-removal safeguards.

In no-discovery mode, confirm eligible Wine Cellar transfers. A skipped entry
stays in Wine Cellar and the scan considers the following candidate.

**Acceptance:** previews and applied mixed transitions agree, recovery preserves
order, and transfer choices preserve capacity and duplicate handling.

## Item 10: add album links to Discographies

**Status:** owner-approved, deployed and verified on 2026-11-05 in PR #82. The
[implementation and review guide](improvements/10_DISCOGRAPHY_ALBUM_LINKS.md)
records exact-edition selection, packing, validation and isolated previews.

Before confirming an artist's releases, allow multiple Spotify album links/URIs.
Resolve and display metadata; allow explicit inclusion outside the fetched
catalogue. Preserve selected edition IDs, deduplicate appropriately, and
recalculate release counts and weekly packing after additions. Preserve the
previous default-count eligibility check before prompting artists to fill the
remaining slots. Accept eligible artists' additions in full and continue toward
the next multiple of ten when necessary; keep the first-artist policy unchanged.

**Acceptance:** additional links, duplicates, alternate editions, unavailable
albums, and invalid references have clear outcomes. The final plan retains the
explicitly selected identities.

## Item 11: plan New Kids releases for new Queue 2 transfers

**Status:** owner-approved, deployed and verified on 2026-11-05 in PR #83. The
[implementation and review guide](improvements/11_NEW_KIDS_RELEASE_PLANS.md)
records ordered selection, accepted transfer recovery, pinned progression and
isolated account/offline previews.

Provide an ordered four-release plan editor. Default to studio albums and EPs;
allow showing singles, compilations, and live albums. Select distinct releases
and their order. Allow a shorter plan with explicit confirmation.

**Owner clarification:** the Queue 2 album is included only if explicitly chosen;
it does not count automatically. New transfers start with the first selected
release. Persist the accepted plan before completing the transfer. Planned artists
immediately use plan-driven execution; Last.fm scrobbles cannot advance, reorder,
or complete their plan. Existing unplanned artists migrate in Item 12.

Preserve track progression, album evaluation, artist completion criteria, logical
artist routing, and mutation safeguards except for explicitly agreed differences.

**Acceptance:** recovery preserves plans and transfers without duplication. An
accepted plan never reaches the old scrobble-driven selector. Unavailable releases
or catalogue changes cannot silently replace a chosen release.

## Item 12: migrate existing New Kids artists

Prompt existing artists without a plan to choose and order one. Include the
current album at its chosen position; earlier plan entries count as completed.
Resume at the current playlist track rather than restarting the current album.
Preserve confirmed migration progress. Back up the namespace and handle existing
active runs at a defined safe boundary. Request resolution when the current
marker cannot be confidently mapped to the selected edition.

**Owner clarification:** automatic inclusion of the current album applies to this
migration only. Shorter plans remain available with confirmation.

**Acceptance:** migration is resumable, completed artists are not prompted again,
and subsequent progression follows the saved plan independently of scrobbles.
