# Item 10: add album links to Discographies

**Status:** implemented and verified; awaiting owner PR review.
**Branch:** `codex/item10-discography-album-links`.
**Roadmap:** [Item 10](../IMPROVEMENTS_ROADMAP.md#item-10-add-album-links-to-discographies).

## Artist review

Web and CLI now allow album additions before confirming each artist's releases.
Paste multiple direct Spotify album links, localized `intl-…` links, Spotify
album URIs or bare album IDs. Spaces, newlines, commas and semicolons separate
references. URL tracking parameters do not change the album identity. Other
resource types, unsupported hosts and short links return an explicit input error.
The application resolves the validated album ID through Spotify; it never follows
an arbitrary pasted URL.

Each successful addition shows its actual title, date, track count, classification,
saved status and artist credits. Links can explicitly include records outside
the fetched catalogue, including another primary artist, singles, compilations
or live releases. The fetched catalogue's existing automatic eligibility and
canonical-edition rules remain unchanged.

Adding selects the resolved option and preserves the submitted state of existing
checkboxes. An exact duplicate ID reuses and selects its existing row without
another metadata lookup. Distinct edition IDs remain separate options and are
never collapsed back to an automatically preferred edition. Both count if both
remain checked; uncheck the earlier edition when the link is a replacement.
Confirmed releases retain chronological order and their exact IDs in the plan,
final Spotify links and the existing successful-application audit.

Every reference receives feedback. Invalid, missing, market-restricted or malformed
albums leave the draft editable and do not discard valid additions from the same
batch. An empty record cannot become a choice. Authentication, rate-limit and
service failures remain under the existing interface/retry policy instead of
being presented as missing albums. Quit or the panel stop control cancels planning
without applying markers or priority changes.

## Packing and final authority

Artist review now precedes the default-count size shortcut in composed web and
CLI runs. Empty catalogues, zero-default catalogues and artists whose fetched
defaults exceed the remaining slots are still offered for editing. Packing uses
the actual confirmed selection count. For example, eight fetched records plus
two linked records fill a ten-release week. A nine-release selection leaves one
slot, and an artist with two defaults can be reduced to one during review.

The prompt shows remaining slots and the current selected count/listening days.
If a reviewed selection exceeds the remaining capacity, the planner reports it
and considers the next artist. It retains the reviewed choice in its existing
per-artist cache. Declined artists are not offered repeatedly. The original first
artist, queue rotation, chronological ties, marker grouping and packing policy
remain intact.

Preview performs the full review and packing without playlist removals or state
writes. A live run still requires the separate final Remove artists / Keep markers
decision. Only that confirmed application uses the existing removal, per-artist
audit and final priority-write boundaries. Adding a link neither saves an album
to the Spotify library nor adds tracks to a playlist.

## Architecture and compatibility

The named `DiscographyReleaseReview` application stage owns read-only draft edits.
It calls pure domain reference/merge rules directly, and uses explicit typed
`DiscographyAlbumAccess` and `DiscographyReviewReader` resources. Bootstrap binds
the existing invocation-owned Spotify client and retry policy to exact album and
saved-status reads. Interfaces present typed drafts and submissions; they do not
hide another application stage inside an integration adapter. No framework,
package, HTTP route or CLI command is added.

Standard web/CLI calls opt into this review stage. Existing custom selectors and
Python compatibility facades keep their prior interface, default-count shortcut
and frozen observation/effect traces. The existing application planning path
without the optional stage remains unchanged.

The existing web pending model adds `release_review`, an opaque request identity,
notices and remaining slots. Options add credits and a linked flag; requests add
album references and the optional proposal identity. New draft submissions require
their exact identity, rejecting missing, stale or wrong-kind actions. Submission
and consumption remain atomic under the owning job's lock/signals. Final artist
results add exact release IDs. All four model changes are additive; existing
properties, routes, commands, namespace defaults and Spotify contracts remain.

Polling preserves the current draft DOM, including unsent text, checkbox edits
and focus. Reload restores posted additions and the submitted checklist state for
the same job. Unsent edits are not durable across a page reload. Drafts remain
process-local, as existing Discographies planning did: a service restart requires
planning again. There is no namespace migration or new durable draft format.
Successfully applied plans already retain the exact release records in audits.

## Owner review

Account preview: <http://127.0.0.1:8767/?review=item10>.
Offline demo: <http://127.0.0.1:8769/?review=item10>.
Unlock text: `discography-review` (any nonempty text works on loopback).
Both use isolated local state, data publications and working files. Keep **Dry
run** checked in the account preview. This item has not been deployed.

The offline demo uses actual routes, workers, application stages and persistence
with synthetic Spotify observations. It starts with Artist's eight default
records in Newfoundland, Beta's two records in Memory Lane and Cedar's eight in
Requeue. Queue 3 also contains an Artist marker. Synthetic Spotify links are not
real listening links. Other routines are outside the fixture's scope.

Suggested offline references:

```text
spotify:album:mmmmmmmmmmmmmmmmmmmmmm
https://open.spotify.com/album/nnnnnnnnnnnnnnnnnnnnnn
spotify:album:mmmmmmmmmmmmmmmmmmmmmm
not-an-album
spotify:album:xxxxxxxxxxxxxxxxxxxxxx
```

1. Plan with Dry run checked. Uncheck Record 1, paste the references and Add albums.
   The deluxe edition and unlisted record should appear with credits. The duplicate
   should reuse its row; invalid and unavailable inputs should have clear feedback.
2. Check that Record 1 stays unchecked and nine releases are selected. Type in
   the link field or tab between controls; polling should retain edits and focus.
   Reload after posting additions: the same draft and checked state should return.
3. Use selected releases. Beta should be offered despite its two defaults and the
   single remaining slot. Uncheck one, then confirm. The final plan should have
   two artists, ten releases and five listening days, with the exact linked IDs
   in its Spotify links.
4. Start again and Quit, or use the panel's stop control. Planning should report
   cancellation. A new invocation should start with the original unedited options.
5. Optional: test live final Keep markers only in the offline demo. Final Remove
   artists affects only its simulated source markers and isolated local priority
   and audit files. Automated checks verify the exact source/Queue 3 removals and
   linked IDs in the successful audit.

No account routine was started during agent verification. Preview and synthetic
files must never be uploaded to production.

## Verification and release

`just ci-test` passes **12,332 tests**, random-order seed **186850**, in 456.73
seconds, with **95.47%** aggregate coverage and independent domain/application
floors passing. Ruff, package typing (718 files), strict typing (472 files),
architecture, dependency, lifecycle and public-interface gates pass. The **79
focused checks** cover references, metadata, exact editions, failure categories,
empty/oversized catalogues, packing, cancellation and actual HTTP/CLI flows.
Another **201 domain/architecture checks** verify the final pure parser and
dependency boundaries. No frozen effect recording was changed.

All 11 public artifacts verify; only the four additive OpenAPI models change.
Wheel verification passes for 718 exact packaged Python/frontend files, 44
commands, 135 wrapped routes and both entry points. Browser checks verify mixed
link outcomes, duplicate reuse, retained edits, reload, keyboard focus, exact
final links, packing, both cancellation controls and 320/390/1120 px layouts.
There is no horizontal overflow; the temporary viewport override was reset.
Preview leaves shared-state bytes unchanged. Final process restarts preserve the
exact state bytes in both environments. Both healthy review servers match all
718 branch files and have 20 idle job-list endpoints.

Deployment and merge await owner approval under [AGENTS.md](../../AGENTS.md).
Verify source CI and idle production jobs, preserve current shared state/data,
and upload only approved runtime files. Verify deployed revision, exact frontend,
startup, health, authentication and independent artifacts before merging.

Rollback restores the preceding runtime/frontend. Cancel process-local planning
jobs first; unconfirmed drafts can be planned again. Retain already completed
marker removals, audits and priority changes, plus unrelated data publications.
No state migration needs reversing. Stop owned idle review servers and clean the
branch after merge, preserving operator files and stashes.
