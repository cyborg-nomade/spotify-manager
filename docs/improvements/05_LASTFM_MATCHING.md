# Item 5: manual matching across Last.fm consumers

**Status:** implemented, owner-approved, deployed and verified on 2026-11-04.
**Release:** [PR #77](https://github.com/cyborg-nomade/spotify-manager/pull/77).
**Approved runtime source:** `4b6e4a5a68f869e997966da75d731b4b228fc334`.
**Space revision:** `612bc78e02f7e82b8941988603aacda65674d6a7`.
**Branch:** `codex/item05-lastfm-manual-matching`.
**Roadmap:** [Item 5](../IMPROVEMENTS_ROADMAP.md#item-5-extend-matching-and-repair-new-years-unresolved-item-handling).

## Consumer inventory and behavior

Automatic qualification remains unchanged. These web and CLI paths now compose
the shared explicit fallback when automatic matching produces no usable result:

| Routine | Historical reference | Manual result | Retained rules |
| --- | --- | --- | --- |
| Found Art | Recommended artist and track, seeded from Last.fm history | Track | Live liked status, prior additions, membership, distinct tracks, artist diversity and requested capacity |
| Something Old, Last.fm mode | An artist's ranked history titles | Track | Historical order and scrobble counts, distinct markers and the empty-playlist recheck before appending |
| Sauvignon | Recommended artist and track | Album from broad track results | Studio album/EP eligibility, heard/previously added exclusions, represented albums and existing ranking |
| Palace of Memory, historical half | Historical artist and album | Album | Saved-edition preference, cursor behavior and the existing first-track cache |
| New Year's routines | Ranked tracks, albums and artist markers | Track or album, as appropriate | Original ranking, primary-artist marker rules, chart order and destination safeguards |

Blast and Daily Mind Radio retain Item 4's integration. Queue's Last.fm discovery
resolves artist identities through its existing artist interaction; it does not
resolve historical track or album names. Slow Listening, Requeue, New Wine and
New Kids use history to evaluate listening/progression while obtaining releases
and tracks through Spotify identities. Those progression changes remain in their
separate roadmap items. Release checks and library analysis likewise do not add
historical title-to-track matching paths.

Broad searches use the available artist, track and album text. Track choices show
the first ten usable search positions, in Spotify order, with full credits,
album and link. Album choices show release title, full credits, date, type and
link. Album-only references use album search. Sauvignon has a track reference,
so its broad track search exposes the associated albums, deduplicated by edition
in first-encounter order. Neither path fills omitted/duplicate rows with results
below position ten or filters manual choices by automatic similarity thresholds.
Malformed pages remain errors. Empty pages require explicit No match or Cancel.

Routine eligibility still applies after explicit mapping. In particular,
Sauvignon shows unfiltered search results but skips a selected ineligible release
with an explanation. It does not turn compilations, live records or decorated
editions into eligible studio releases. Found Art refreshes the selected track's
liked status. Something Old completes with `no match` and no append if every
ranked title is rejected. Noninteractive compatibility calls retain their
previous unresolved-item behavior when no interaction owner is supplied.

Owner review also requested two panel changes: Blast's Cap input now defaults to
40, and Found Art has a checked-by-default Dry run checkbox. Its web request
passes the selected mode through job registration and the worker to the existing
recommendation use case. Preview outcomes report proposed additions as **Would
add**, keep the actual playlist length unchanged, and restore/lock the selected
mode while reconnecting to an active run. As in its existing CLI preview, local
recommendation cache and audit updates remain available. Direct API requests
that omit `dry_run` retain their existing live default.

## New Year's plan and the Chevelle report

Every unresolved ranked entry can now be explicitly selected or dropped. Dropped
entries retain their original ranking/scrobble information, have `dropped: true`
and no URI, and remain visible in the final preview. Chart creation and destination
application exclude them. Rejecting one entry does not abort the remaining plan.
If no ranked track provides an artist's primary marker, an artist-only track
search allows explicit selection or dropping that artist. A marker for a different
primary artist is explained and offered again rather than silently accepted.

During one planning pass, accepted/rejected ranked tracks are reused when planning
artist markers. Dry run follows all decisions and produces the complete plan
without creating charts or changing Spotify playlists. Live runs persist the
resolved plan through the existing annual recovery boundary before application;
resuming that plan does not repeat completed matching decisions. An interrupted
planning pass has no new durable choice checkpoint and is rebuilt on the next run.

Three read-only Spotify queries established the reported Chevelle cause:

- `track:"In Debt to Earth" artist:"Chevelle"` returned both **In Debt to the
  Earth** on **Vena Sera** and **In Debt To The Earth** on **12 Bloody Spies:
  B-sides and Rarities**.
- Broad `Chevelle In Debt to Earth` returned ten results, with those two first.
- The strict query containing the corrected title also returned both records.

The existing normalization gives the omitted-article title similarity
`0.896551724137931`, below the unchanged `0.9` automatic threshold. Availability
was not the failure. The regression fixture
[`chevelle.json`](../../tests/fixtures/catalog_matching/chevelle.json) preserves
parser-relevant public catalog metadata from those responses. It contains no
credentials or account data. The regression resolves the observed first result
through the generic fallback without a Chevelle-specific rule.

## Architecture and interaction contract

Named application stages own track/album fallback decisions; concrete catalogs
own broad Spotify reads. Bootstrap composes them with the existing invocation's
request policy, cancellation and web/CLI interaction resource. Sauvignon's policy
is still resolved after request validation. Something Old calls its named Last.fm
selection stage directly. No application stage is hidden inside an integration
adapter, and no execution callbacks or new runtime dependencies are introduced.

The existing `track_match_pending_choice` channel gains additive `kind` and
`albums` fields. Its default remains `track`, preserving Item 4 consumers. The
following POST endpoints accept the same request-token/choice JSON protocol:

- `/commands/found-art-jobs/{job_id}/match`
- `/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/match`
- `/commands/something-old-jobs/{job_id}/match`
- `/commands/fill-palace-of-memory-jobs/{job_id}/match`
- `/commands/new-year-jobs/{job_id}/match`

Found Art also gains `/commands/found-art-jobs/{job_id}/cancel`. Existing
artist/mode/edition choice endpoints remain separate. Handler validation covers
command ownership, waiting status, current token and offered identity; stale
submissions return 409 and unoffered identities return 400. An empty choice means
No match. Cancellation wins before consumption, wakes pending work and clears
the prompt. Polling preserves focus for an unchanged prompt; reload restores it
within the same server process. Pending jobs remain process-local.

CLI choices suspend progress displays, show numbered results with copyable URLs,
and accept a number, `n` for No match or `q` to cancel, with no implicit choice.
Found Art's internal operation groups its four paths in `FoundArtResources`;
its external routine compatibility signature retains the original path arguments.

## Owner review

Account preview: <http://127.0.0.1:8767/?review=item05>.
Offline review: <http://127.0.0.1:8769/?review=item05>.
Unlock text: `catalog-matching-review` (any nonempty value works on loopback).
Both use isolated working files and local state/data stores. Keep Dry run checked
when using the account preview, including Found Art.
The offline environment runs real application stages and HTTP workers against
synthetic external clients and public Chevelle observations; it makes no live
Spotify, Last.fm or Random.org requests. Other panels are outside its fixture scope.

1. In the offline environment, run New Year with Dry run selected. Select the
   first Chevelle track, then the desired album; inspect the completed rankings
   and Spotify marker links.
2. Run again and use **No match · drop this entry** for the track, album and
   artist marker. The preview should complete with visibly dropped entries.
3. Reload while waiting, then select or cancel. The pending request should return
   in the same order; cancellation should clear it.
4. Something Old offers its original mode choice before its new track fallback.
   Choose Last.fm top tracks, then select or reject the title. Sauvignon presents
   album choices. Palace first refreshes the synthetic saved releases before
   reaching historical album choices.
5. Found Art can be tested against simulated playlist effects in the offline
   environment. Its requested title deliberately differs from the offered catalog
   title to demonstrate explicit mapping below the automatic threshold.
6. Check a narrow mobile viewport, candidate metadata, Spotify links and both
   decision controls. Tab from a candidate to its link and verify polling retains
   focus.

## Validation and release

Completed verification:

- GitHub CI [41817830259](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41817830259)
  passes both jobs for the exact approved runtime source: **12,005 tests**, seed
  `346626`, 779.72 seconds. Package/strict typing, Ruff, architecture, frozen
  interfaces, packaging and independent coverage gates pass. Package coverage
  clears its 95% statement / 90% branch floors; domain and application each clear
  98% / 95%. The existing Starlette TestClient deprecation warning remains.
- **143 focused API/interface tests** pass for Found Art's preview/live paths,
  including manual selection/rejection/cancellation and empty recommendations.
  **1,253 lifecycle and call-path checks** pass with the explicit preview launch
  argument. The full suite also covers New Year web/CLI selection, dropping and
  cancellation, Sauvignon CLI album choices, and Something Old's real all-rejected
  CLI outcome.
- **11 public artifacts** match after the intended additive baseline updates.
  `just verify-wheel` verifies **701 packaged Python/frontend files**, **44 CLI
  commands**, **134 wrapped routes**, imports and both entry points.
- Domain/application checks retain routine eligibility, duplicates, ordering,
  saved-edition priority, marker identity, explicit-drop recovery and preview
  write suppression. Interaction races cover all five new submission endpoints
  with both track and album candidates.
- Browser checks use real application stages and workers with synthetic external
  services: New Year selection/drop-all/cancel; Found Art selection; Something
  Old mode selection and rejection; Sauvignon album rejection; Palace album
  selection, no-match continuation and cancellation. New Year, Something Old,
  Sauvignon and Palace restore the same pending request after reload. Shared
  polling retains keyboard focus. Blast selection and Daily rejection/cancellation
  still work after the common interaction changes.
- Matching lists have no horizontal overflow at 320, 390, 760, 1120 and 1440
  pixels. A 390-pixel album check verifies both options, dates/types, links and
  decision buttons. The saved mobile screenshot shows this interaction.
- Owner-review browser checks confirm Cap defaults to 40 and Found Art defaults
  to checked Dry run. A manually selected preview reports **Would add 1** with
  playlist **0 -> 0**. Reload restores both checked preview and unchecked live
  modes while keeping the control locked during the job; live cancellation
  clears the pending prompt. Both updated panels fit at 320 and 390 pixels.
- Both preview servers pass health checks, serve all **701 identical branch
  runtime files** and the exact frontend, and are idle across all **20** job-list
  endpoints. Browser verification made no live service requests. The Chevelle
  investigation used only the three read-only catalog queries described above.

Intentional contract changes are six additive routes, album option schema,
additive pending fields and their route counts, and Found Art's optional
`dry_run` query parameter. Its frozen job-launch observation adds the preview
flag; all other fields remain intact. The Spotify endpoint inventory is unchanged.

This item introduces no operational data migration or environment changes.
The annual plan adds an optional explicit-drop flag; old plans remain readable.
Existing saved plans are retained rather than rebuilt silently. Local preview
state and files must never be uploaded to production.

The owner approved PR #77, including Cap 40 and Found Art's web Dry run, on
2026-11-04. Authenticated preflight
[41828165408](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41828165408)
and postflight
[41828547440](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41828547440)
verified automation access, shared state, all four artifacts and no active jobs
across 20 endpoints. Neither check started history scans or playlist routines.

Only the **58 approved runtime files** were uploaded, including six new modules,
with a guarded parent revision. All **77 cumulative release blobs**, the running
Space revision, exact served frontend, health and the new controls were verified.
State stayed at `622d1ac69df56633e40288c2345df9e37c1ec8e7`; canonical data stayed at
`d8c6e548758f1a134c9d2bed65edf1cd2f0e6d60`. Credentials and unrelated operational
files were excluded. The remaining release-tracking changes are documentation
only; merge and cleanup follow [AGENTS.md](../../AGENTS.md).

Rollback restores the
previous runtime/frontend while preserving independent data publications and
annual state. Saved plans containing explicit drops must not be applied by an
older runtime that does not understand them; finish or retain those plans before
rolling back. Stop the owned idle preview servers during post-merge cleanup.
