# Round 2, item 1: chronological New Kids planning catalogue

**Status:** owner-approved, deployed and verified on 2026-11-09 in
[PR #85](https://github.com/cyborg-nomade/spotify-manager/pull/85).
**Branch:** `codex/round2-item1-new-kids-chronology`.
**Roadmap:** [second-round item 1](../IMPROVEMENTS_ROADMAP_2.md#item-1-chronological-new-kids-planning-catalogue).

## Behavior

Available releases in the New Kids plan editor are ordered by release date,
oldest first, then case-insensitive title when dates coincide. Exact IDs break
remaining ties deterministically. The same ordering reaches web and CLI drafts
for New Kids/Queue 2 transfers and existing-artist migration.

Year-only dates compare as January 1, month-only dates as the first of that month;
unknown and calendar-invalid dates come last and compare by title/ID. Displayed
date text and precision are preserved. Studios/EPs remain the default visible
categories. Enabling singles, live albums or compilations reveals their proper
chronological positions in the same catalogue.

Canonical edition choice, release eligibility, popularity observations and exact
release IDs remain unchanged. Only planning presentation is sorted. The selected
listening order remains explicitly controlled by the operator; saved plans and
their cursor are never reordered. Migration still identifies and preselects the
exact current album before sorting its displayed catalogue. The current album
need not be the first catalogue row.

The existing polling, keyboard, scrolling, shorter-plan confirmation,
current-album locking and skip/quit behavior remain. No new route, command,
OpenAPI field, dependency or state migration is introduced.

## Implementation

`domain.new_kids_plans.planning_catalogue` owns the ordering rule, reusing the
existing calendar-valid first-day date key and keeping title before raw-date or
ID tie-breaks. Both named selection stages call it directly when creating drafts.
The migration stage resolves its current edition first, preserving the existing
identification and unique-track confirmation behavior.

The only callback is the standard-library `sorted` key; its reason is documented
beside the call. No execution dependency or bootstrap wiring is added.

## Owner review (completed)

- [Account preview](http://127.0.0.1:8767/?review=round2-item1): keep Dry run checked.
- [Offline demo](http://127.0.0.1:8769/?review=round2-item1): synthetic services only.
- Unlock text: `chronology-review`.

Both use isolated local state, canonical files and durable-data publications.
The account environment begins with a copy of the current shared-state snapshot;
no account routine is started by the agent. Preview and fixture files stay outside
the repository and release.

The offline demo begins with Artist at Second studio track 1 and New Artist in
Queue 2. Their catalogue deliberately disagrees with popularity/tier ordering:
Single 1990, EP 1998, Second studio 1999, Fourth/Third studio 2001 (alphabetical
tie), First studio 2003, Live 2005, Queue album 2010, Compilation Unknown.

1. Run New Kids in Dry run. Migration should preselect Second studio while the
   visible catalogue begins with An EP. Fourth precedes Third for their equal dates.
2. Enable optional categories. The single appears first and the undated
   compilation last. Selection and scroll position should survive polling.
3. Choose First → Second → Third → Fourth. This order stays as chosen even though
   it differs from the catalogue. Accept it to continue to prefill.
4. Prefill offers a plan for New Artist, with the same chronology and no
   preselection. Once both choices are accepted, the preview advances the existing
   marker from Second track 1 to track 2. The new artist stays on the first track
   of its first chosen release until a later run. A dry run saves neither plan
   nor Spotify effects.
5. Quit/skip and the panel stop control retain their previous behavior. Queue 2
   also uses the chronological editor for new transfers.

## Verification and release

`just ci-test` passes **12,441 tests**, random-order seed **404592**, in **512.19
seconds**, with **95.38%** aggregate coverage. Independent package, domain and
application statement/branch floors pass. Ruff (727 files), package typing
(729 files), strict typing (485 files), dependency, structure and lifecycle
gates pass. The **83 focused checks** include pure ordering, migration, transfers,
recovery and actual HTTP/CLI paths.

All **11 public artifacts** verify unchanged. Wheel verification passes for
**729** exact runtime files, **44** commands, **135** wrapped routes and both
entry points. The frontend source and API schemas are unchanged.

Browser checks cover migration and transfer catalogues, optional category
chronology, equal-date alphabetical ordering, explicit nonchronological plan
selection, polling focus/scroll retention (580 px), Queue 2 cancellation and
320/390/1280 px layouts without overflow or console errors. The viewport override
was reset. Both review runtimes have exact branch files, healthy services and
**20 idle job endpoints**. No account routine was started.

The combined offline dry run preserved both explicit orders, advanced the existing
artist from Second track 1 to track 2, and left the transferred artist at First
track 1. No artist plans, migration backup or synthetic remote mutations were
saved. The initial fixture remains ready for owner review.

The owner approved PR #85 on 2026-11-09.
[Source CI 42586637598](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42586637598)
passed all **12,441 tests**, seed **257920**, with independent
statement/branch floors passing. Typing, architecture, lifecycle, interface and
packaging gates passed.

Authenticated [preflight 42587786972](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42587786972)
and [postflight 42588616731](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42588616731)
confirmed automation access, shared state, all four canonical artifacts and
**20 idle routine endpoints**. Neither check started a routine.

Only the **three approved runtime files** were uploaded, with the prior Space
revision and prior blobs guarded. There are no new modules. Space revision
`993522905d6384a84f2f7d9760d31eacc2537ef7` is running; all **164 cumulative
release blobs**, exact frontend, runtime identity and health were verified.
Shared state stayed at `ace561202e4d4fd28924b14a4f127f8907029066`; canonical data stayed at
`7275bd794de01e5ab8b541ce6b5535837a7d267a`. Preview/synthetic files, operational files and credentials
were excluded. The approved runtime source remains `fc0aef1ae1ea6a3932aff927628828fdca800bf0`;
subsequent release tracking is documentation only.

Rollback restores the three prior runtime blobs without changing accepted plans,
progress, state or canonical data. Review servers are retired after approval and
idle-job verification; their local files and private evidence are retained.
