# Item 10: add album links to Discographies

**Status:** owner-approved, deployed and verified on 2026-11-05 in PR #82.
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

After the first artist, the previous default-count eligibility check runs before
review: an artist must have at least one default release and no more defaults
than the remaining weekly slots. With two slots free, a seven-record discography
is skipped without prompting. Empty and zero-default filler catalogues are also
skipped. The original first-artist policy is unchanged, including the opportunity
to add links when that first catalogue is empty.

The prompt shows remaining slots and the current selected count/listening days.
An eligible artist's confirmed selection is accepted in full, including extra
albums that exceed those slots. Packing then continues toward the next multiple
of ten. For example, eight records followed by an eligible two-record artist with
one addition make eleven; the planner looks for nine more records to reach twenty.
Previously oversized artists can become eligible against this new capacity.
Declined artists are not offered repeatedly. Queue rotation, chronological ties
and marker grouping remain intact.

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
Both used isolated local state, data publications and working files. These owned
review servers were stopped after approval and deployment; their files remain
local. The approved runtime is now deployed.

The offline demo uses actual routes, workers, application stages and persistence
with synthetic Spotify observations. It starts with Artist's eight default
records in Newfoundland, Beta's two records in Memory Lane and Cedar's nine in
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

1. Plan with Dry run checked. Keep the eight defaults checked, paste the references
   and Add albums.
   The deluxe edition and unlisted record should appear with credits. The duplicate
   should reuse its row; invalid and unavailable inputs should have clear feedback.
2. Check that ten releases are selected. Type in
   the link field or tab between controls; polling should retain edits and focus.
   Reload after posting additions: the same draft and checked state should return.
3. Use selected releases. The final plan should have one artist, ten releases and
   five listening days, with the exact linked IDs in its Spotify links.
4. Start again and accept Artist's eight defaults without additions. Beta should
   be offered for the two remaining slots. Add just the first reference above,
   keep all three releases selected and confirm. Cedar should then be offered
   for nine remaining slots. Accept its defaults: the final plan should have
   three artists, twenty releases and ten listening days.
5. To check the original eligibility filter, start again and deselect one of
   Artist's eight defaults. After confirming seven records, Beta's two fit; after
   confirming those, Cedar's nine cannot fit the single remaining slot and should
   be skipped without prompting. The final plan has nine releases and one open slot.
6. Start again and Quit, or use the panel's stop control. Planning should report
   cancellation. A new invocation should start with the original unedited options.
7. Optional: test live final Keep markers only in the offline demo. Final Remove
   artists affects only its simulated source markers and isolated local priority
   and audit files. Automated checks verify the exact source/Queue 3 removals and
   linked IDs in the successful audit.

No account routine was started during agent verification. Preview and synthetic
files must never be uploaded to production.

## Verification and release

`just ci-test` passes **12,338 tests**, random-order seed **869866**, in 473.76
seconds, with **95.47%** aggregate coverage and independent domain/application
floors passing. Ruff, package typing (718 files), strict typing (472 files),
architecture, dependency, lifecycle and public-interface gates pass. The **85
focused checks** cover references, metadata, exact editions, failure categories,
first-artist additions, skipped empty/oversized fillers, packing through twenty
and thirty releases, cancellation and actual HTTP/CLI flows. A further **87
planning and interface checks** include the original frozen planning sequences.
No frozen effect recording was changed.

All 11 public artifacts verify; only the four additive OpenAPI models change.
Wheel verification passes for 718 exact packaged Python/frontend files, 44
commands, 135 wrapped routes and both entry points. The updated browser check
confirms eight initial records, two eligible defaults with an added exact edition,
reload retaining all three selections, and nine further records completing twenty
releases over ten days. The exact linked ID survives in the final result; there
are no browser console errors. The temporary viewport override was reset.
Earlier Item 10 browser checks cover mixed link outcomes, duplicate reuse,
unchecked editions, polling/focus, both cancellation controls and responsive
layouts. The correction changes packing and explanatory text, without CSS changes.
Preview leaves shared-state bytes unchanged. Both process restarts preserve the
exact state bytes in both environments. Both healthy review servers match all
718 branch files and have 20 idle job-list endpoints.

The owner approved PR #82 after reviewing the restored eligibility filter.
[Source CI 42032119290](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42032119290)
passed all **12,338 tests**, random-order seed **84510**, in 868.53 seconds, plus
typing, architecture, interface, packaging and independent coverage gates.

Authenticated [preflight 42033257887](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42033257887)
and [postflight 42034797170](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42034797170)
verified automation access, shared state, all four data artifacts and no active
jobs across **20** routine endpoints. Neither check started a routine.

Only the **16 approved runtime files**, including four new modules, were uploaded
with a guarded parent revision and verified prior blobs. Space revision
`27d182c1bceee4600b3eed42c848c5a982cbc3a0` is running; all **141 cumulative release
blobs**, exact served frontend, startup, health and protected authentication were
verified. State stayed at `45f409930215adf29d185b769453b337dc478eca`; canonical data
stayed at `96c1caba1f8e6c5dadccd677cc2f1b03bed957d1`. Credentials, operational files
and all preview/synthetic state were excluded. Both owned review servers were
stopped after verifying their 20 idle endpoints. Local data and operator stashes
were preserved. Remaining release tracking is documentation only; merge and
branch cleanup follow [AGENTS.md](../../AGENTS.md).

Rollback restores the preceding runtime/frontend. Cancel process-local planning
jobs first; unconfirmed drafts can be planned again. Retain already completed
marker removals, audits and priority changes, plus unrelated data publications.
No state migration needs reversing. Stop owned idle review servers and clean the
branch after merge, preserving operator files and stashes.
