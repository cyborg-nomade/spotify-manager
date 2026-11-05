# Item 11: explicit New Kids plans for new Queue 2 transfers

**Status:** implemented; awaiting owner PR review.
**Branch:** `codex/item11-new-kids-release-plans`.
**Roadmap:** [Item 11](../IMPROVEMENTS_ROADMAP.md#item-11-plan-new-kids-releases-for-new-queue-2-transfers).

## Operator flow

New Kids and Queue 2 now request a release plan before transferring a new artist
from Queue 2. The editor starts with studio albums and EPs from the existing
canonical primary-artist catalogue. Singles, compilations and live releases can
be shown independently. Add up to four distinct releases, then use Move up,
Move down and Remove to arrange the listening order. Catalogue ranking does not
override that explicit order.

Nothing is preselected. The current Queue 2 album appears as context and counts
only if explicitly selected. Confirming a live plan starts at the first playable
primary-artist track of the first selected release. Newly transferred artists
remain on that initial track until the next invocation, including prefill artists;
they do not immediately advance during the invocation that starts their plan.

A one-, two- or three-release plan requires the separate shorter-plan confirmation.
An empty plan, more than four entries, repeated IDs or unknown IDs cannot be
accepted. Skip transfer leaves that artist in Queue 2 and considers later artists;
the same artist is not prompted again during final refill in that invocation.
Quit or the panel stop control stops before another unaccepted transfer. Earlier
accepted effects and their saved progress remain available to resume.

The CLI shows studio albums/EPs first. Enter release numbers in listening order,
or `all` to include every optional category. Confirm the displayed order explicitly;
short selections use a distinct shorter-plan confirmation. `s` skips the transfer
and `q` stops. Web submissions carry the exact current proposal identity, so a
stale tab or repeat click cannot accept another draft.

Polling retains ordering, filters, shorter confirmation, keyboard focus and the
catalogue's scroll position. Scrolling partway down or to the last release does
not reset when a job update arrives.
Unsubmitted web edits are process-local form state and reset on page reload;
accepted plans are durable. No plan or transfer is saved by a dry run. The existing
shared Last.fm history refresh remains part of discovery preflight, including
previews; it does not determine progression for a planned artist.

## Durable execution and recovery

An additive `release_plan` field in the existing New Kids artist record stores
version 1, exact serialized releases in explicit order and the zero-based current
position. It uses a distinct key from the obsolete historical selection fields
that the existing progress reader removes. Existing namespace versioning and
unrelated fields remain intact. Existing artists without this key retain their
current behavior until the separately approved Item 12 migration.

Before any transfer append or removal, one checkpoint stores the accepted artist
plan and a `release_plan_transfers` intent. The intent pins source/destination
playlists, logical artist, original Queue 2 marker and first chosen destination
marker. Append secures the destination before removing the source. A subsequent
checkpoint acknowledges the transfer and clears its intent.

Recovery loads the accepted plan and observes both playlists. An existing exact
target is reused, including after a lost append acknowledgement; a removed source
is not recreated. Playlist changes, an inconsistent saved plan, conflicting artist
membership/capacity or neither marker being present require resolution. They do
not trigger another selection or silently replace the first release. Duplicates
for artists already in New Kids retain the existing reconciliation behavior.

Planned artists bypass both composer-choice routing and the annual played-release
selector. Within an album, the original track order, liked-track shortcut and
unliked streak remain. At the release boundary, the original album evaluation
and library reconciliation remain. The next exact pinned release supplies its
first playable primary-artist track, and its position is acknowledged with the
existing review-entry checkpoint. Saved transition replay sets that same position,
rather than incrementing it again. Last.fm scrobbles cannot skip, reorder or finish
the plan. Catalogue recanonicalization cannot substitute another release ID.

Spotify read failures, a pinned release with no primary-artist tracks, or an
unrecognized current marker stop with the saved plan retained. An exact track in
the pinned release can carry different playlist album metadata; its track
membership retains the chosen release identity. This guard accommodates the
possibility described by Spotify's [track-relinking model](https://developer.spotify.com/documentation/web-api/concepts/track-relinking)
without accepting an unrelated marker. Exhausting the selected order reaches the existing
live artist assessment and promotion/unlucky/unfollow rules. Completed artists
are removed from progress as before. Preview refill projects reviewed markers,
accepted transfers and logical composer credits in memory without changing saved
plans or remote playlists.

## Architecture and compatibility

Pure `domain.new_kids_plans` rules validate ordered IDs and adapt the first marker.
The named `NewKidsPlanSelection` application stage reads catalogues and typed
`ReleasePlanReader` submissions. `PlannedDiscoveryTransfers` extends the existing
transfer resources with durable intent and preview projection. Bootstrap selects
this stage when the standard web/CLI supplies its editor. No client is constructed
inside a routine, and no execution dependency is a function or bound method.

Existing custom selectors and Python compatibility facades keep their previous
transfer behavior unless an editor is supplied. Saved-plan progression is detected
by the shared planner independently of that opt-in. The existing successful
observation/effect fixtures remain unchanged. No route, command, framework,
package or namespace migration is introduced.

Only `NewKidsPendingChoice` and `NewKidsChoiceRequest` receive additive OpenAPI
properties. Existing properties, required fields, route contracts, commands and
defaults remain. The owning job lock accepts and consumes a complete typed plan;
the existing cancellation signal interrupts its wait and Spotify retry boundaries.

## Owner review

- [Account preview](http://127.0.0.1:8767/?review=item11): keep **Dry run** checked.
- [Offline demo](http://127.0.0.1:8769/?review=item11): synthetic Spotify/Last.fm only.
- Unlock text: `release-plan-review`.

Both environments use isolated local state, mirrors, history and durable-data
publications. The agent did not start an account routine. This item is not deployed.

The offline fixture has one Queue 2 artist and an empty New Kids playlist. Its
catalogue contains four studios, an EP, a single, a live album, a compilation and
the separate Queue album. Links/IDs are synthetic. Other routines are outside its
scope. Its simulated remote effects survive server restart. Live verification
is archived, and the initial fixture has been restored for review.

1. Run New Kids with Dry run checked. Verify no releases are preselected and only
   studios/EPs appear. Toggle the three optional categories independently.
2. Add an EP, studios and an optional release. Change their order and remove/re-add
   one. Four selections enable Use this plan. With three, that button requires the
   explicit shorter-plan checkbox. Polling should retain edits and keyboard focus.
3. Accept the preview. It should transfer one projected artist to the first track
   of the first chosen release, with zero immediate artist decisions and no repeat
   final-fill transfer. Repeat through Queue 2 to review its prefill interaction.
4. Start again and Quit, or use the panel stop control. Neither unaccepted plan
   should change playlists or saved artist progress.
5. Optional, offline only: uncheck Dry run, choose an order and accept. The first
   track remains until the next Run. Further runs advance within that album and
   then follow the selected order without another release-choice prompt. The
   accepted plan and simulated remote both survive a process restart.

## Verification and release

`just ci-test` passes **12,391 tests**, random-order seed **162238**, in 498.27
seconds with **95.40%** aggregate coverage and independent domain/application
floors passing. Ruff (723 files), package typing (725 files), strict typing (479
files), architecture, dependency, lifecycle and public-interface gates pass.

The **48 focused checks** cover plan order/categories/bounds, explicit shorter confirmation,
skip/quit, persistence before effects, failed/lost append and removal acknowledgements,
restart/reload, current-marker mismatches, unavailable pinned releases, track and
release advancement, completion assessment and actual HTTP/CLI paths. A further
**98 focused/planning checks** pass, including pinned-marker rules, original
planner/review behavior and the structure guard. Existing
New Kids/Queue 2 frozen planning and execution sequences pass unchanged.

All 11 public artifacts verify, with only the two additive models changed. Wheel
verification passes for 725 exact packaged Python/frontend files, 44 commands,
135 wrapped routes and both entry points. Browser verification covers explicit
ordering, optional categories, shorter confirmation, retained polling focus,
both stop controls and 320/390/1120 px layouts without horizontal overflow. The
temporary viewport override was reset, and there are no console errors.

The catalogue-scroll correction was verified in both New Kids and Queue 2 through
repeated live polling, including middle/bottom positions, optional categories and
selection at the bottom. The 26 public-interface/capture checks pass, and the
wheel was rebuilt and verified with the corrected frontend. No Python behavior
or API schema changed for this correction.

Offline live verification accepted the exact studio/single/EP/live order, secured
the first chosen marker once, then restarted the actual server. State and remote
bytes were identical after restart. Later runs advanced within the studio album
and then started the pinned single with no additional choices. The fixture was
restored afterward. No preview, credential or synthetic data may be uploaded.

Deployment and merge await owner approval under [AGENTS.md](../../AGENTS.md).
After approval, verify source CI and idle production jobs, preserve independent
state/data revisions, and deploy only approved runtime files. Verify the running
revision, exact frontend, health, authentication and durable artifacts before merge.

Rollback requires stopping New Kids and Queue 2 and preserving accepted plans,
pending transfer intents and already completed effects. An older runtime ignores
the additive plan fields and must not resume those planned artists. Keep their
execution stopped until a runtime that honors the saved plans is restored; no namespace version
migration needs reversing. Preserve operator files and stashes during cleanup.
