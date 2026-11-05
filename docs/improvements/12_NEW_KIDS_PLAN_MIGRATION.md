# Item 12: migrate existing New Kids artists

**Status:** implemented and verified; owner review pending.
**Branch:** `codex/item12-new-kids-plan-migration`.
**Roadmap:** [Item 12](../IMPROVEMENTS_ROADMAP.md#item-12-migrate-existing-new-kids-artists).

## Operator flow

At a fresh New Kids run, existing artists without a saved release plan receive
an ordered plan editor before transfers or advancement. The exact current album
is included and preselected when its current track can be identified. It can be
moved in the order, but cannot be removed. Select up to four distinct releases;
confirm explicitly to use fewer. Studios and EPs appear first, with independent
single, compilation and live filters. The current album remains visible even
when its category is hidden.

Entries before the current album count as completed. The current album counts
as one of the chosen releases, and progression starts at the track already in
the playlist. Accepting a migration itself does not change that marker. Once all
migration choices finish, the ordinary run advances once from the current track
using the selected plan and existing liked/unliked-track rules. It does not
restart the album. Later runs follow the saved order independently of scrobbles.

An artist transferred from Queue 2 retains Item 11 behavior: no album is
preselected, the queue album counts only if explicitly chosen, and listening
starts at the first selected release. Queue 2 does not migrate existing New Kids
artists; run New Kids to migrate them.

Skip artist this run leaves that artist unplanned and excludes it from this
invocation's review. A later fresh run offers it again. Quit or the panel stop
control retains plans already accepted for earlier artists. Unsubmitted edits
remain local to the page and are lost on reload. Polling retains the editor,
selection, filters, keyboard focus and catalogue scroll position.

The CLI uses the same plan validation. Enter release numbers in listening order,
confirm the order (or shorter plan), use `all` for optional categories, `s` to
skip this artist and `q` to quit. A migration explains the current album/track
and how earlier entries count as complete.

## Edition resolution

The current exact edition remains a candidate even if canonical catalogue
selection omitted it. Matching the current track ID makes that edition known.
When it cannot be identified, the editor requires an explicit current-edition
choice and confirmation. The chosen edition must be included in the ordered
plan and contain either the exact track ID or one uniquely matching normalized
title. Duplicate title matches and missing tracks require another choice;
they cannot silently restart or finish the album. The CLI asks for the current
album's position in the chosen order and then explicit track confirmation.

Only Spotify 404/410 responses from exact release reads become recoverable
edition-resolution choices. Authentication, rate limits and service failures
retain the existing retry/error policy. Current composer routes retain their
logical artist identity and performer credit; pinned plan progression updates
that route as its markers change.

## Persistence and safe boundaries

Before the first accepted migration writes artist progress, a separate durable
checkpoint stores `release_plan_migration_backup` in the New Kids namespace.
Its version 1 record contains a UTC `created_at` and a deep copy of the complete
pre-migration `namespace`. It is created once and retained by subsequent saves;
an invalid existing backup blocks migration rather than overwriting it. Other
namespaces and canonical artifacts are untouched by this migration checkpoint.

Each accepted artist plan is saved independently using the existing version 1
`release_plan` schema, with its zero-based position set to the current album.
Earlier accepted artists are not prompted again after cancellation or restart.
Existing unliked streaks and unrelated artist fields remain. A one-time
`release_plan_marker` pins the explicitly validated current marker/edition;
the normal acknowledged transition removes it. Existing review checkpoints and
replay semantics continue to own playlist and library effects.

A real saved active/refilling New Kids run resumes its accepted snapshot before
migration. The output explains that migration begins at the next fresh run.
An active Queue 2 run still blocks New Kids before any migration interaction.
This avoids changing the meaning of accepted transitions midway through replay.
Dry runs build plans only in a detached state projection: no migration backup,
plan checkpoint or playlist mutation is saved. The shared Last.fm history
refresh still runs as discovery preflight, but cannot determine planned release
progression. Custom Python selectors without an editor retain their frozen
legacy behavior.

## Architecture and compatibility

`domain.new_kids_migration` owns current-position and unique-track rules.
`NewKidsMigrationSelection` resolves catalogue observations and typed editor
submissions. `NewKidsPlanMigration` owns per-artist persistence and the one-time
backup. `DiscoveryRun` invokes that named stage only at its fresh-run boundary;
bootstrap composes concrete resources. The infrastructure adapter translates
only missing-edition errors. No execution callbacks or client construction are
introduced into application execution or legacy routines.

Only `NewKidsPendingChoice` and `NewKidsChoiceRequest` gain additive OpenAPI
properties. Existing properties, required fields, routes, commands and defaults
remain unchanged. No dependency, namespace version or new endpoint is needed.

## Owner review

- [Account preview](http://127.0.0.1:8767/?review=item12): keep **Dry run** checked.
- [Offline demo](http://127.0.0.1:8769/?review=item12): synthetic Spotify/Last.fm.
- Unlock text: `plan-migration-review`.

Both environments use isolated local state, mirrors, history and durable data.
The agent does not start account routines. The offline fixture begins with one
unplanned existing artist at **Second studio · track 1**, an empty Queue 2 and a
catalogue with studios, an EP and optional categories. Other routines are outside
the fixture's scope. Its simulated remote changes persist across server restart.

1. Run New Kids with Dry run checked. Second studio should be preselected and
   locked against removal. Add First, Third and Fourth studio, then move First
   before Second. Verify polling preserves edits and scroll position.
2. Accept. The preview should advance from Second studio track 1 to track 2,
   with album one considered complete. No plan is saved by the preview.
3. Run again and skip or quit. The unaccepted artist should not advance.
4. Offline only, uncheck Dry run and accept the same order. Further runs advance
   to Third studio without another migration prompt. Shorter orders require the
   explicit shorter-plan checkbox.

## Verification and release

The **58 focused checks** pass across domain rules, per-artist checkpoints,
backup failure/corruption, skip/quit/resume, saved-run boundaries, exact edition
retention, composer credit, missing-edition error translation and actual HTTP/CLI
execution. Both plain and normalized edition-qualified title mappings reach
subsequent progression. The older integration slice now submits an explicit
migration plan for New Kids; Queue 2 retains its original choice contract.

All **11 public artifacts** verify. The two choice models gain properties only;
existing fields, required values and paths are unchanged. Wheel verification
passes for **729** exact Python/frontend files, **44** commands, **135** wrapped
routes and both entry points. `just ci-test` passes **12,427 tests**, random-order
seed **697342**, in **491.05 seconds**, with **95.38%** aggregate coverage and
independent package, domain and application statement/branch floors passing.
Ruff (727 files), package typing (729 files), strict typing (484 files), dependency,
architecture, lifecycle and interface gates pass.

Browser verification covers preselected/locked current albums, ordering, shorter
confirmation, explicit unknown-edition resolution, skip/quit, repeated polling,
retained focus and catalogue scroll, and 320/390/1120 px layouts without horizontal
overflow or console errors. Temporary viewport overrides were reset. Both servers
serve exact runtime copies and the expected schema, with 20 idle job endpoints.
No account routine was started by the agent.

Offline live verification saved the pre-migration namespace before the accepted
plan, advanced from Second studio track 1 to track 2, and restarted the actual
server. State and synthetic remote bytes survived unchanged. A later run started
Third studio without another prompt or duplicate append. The initial fixture was
restored, and all verification artifacts remain private local files.

Deployment and merge wait for owner approval. Preview files, synthetic data and
credentials are excluded from the pull request and release.

Rollback must preserve the backup, accepted plans, active review entries and
completed remote effects. Stop New Kids/Queue 2 before rolling back to a runtime
that ignores explicit plans; keep those artists stopped until a compatible
runtime is restored. Do not automatically replace the live namespace with the
backup after playlist effects have occurred. Preserve operational files and
stashes during release cleanup.
