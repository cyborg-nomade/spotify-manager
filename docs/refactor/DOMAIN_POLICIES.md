# Item 3: pure listening policies

**Status:** approved, deployed, and merged as PR #62 on 2026-09-25.
The source baseline for this extraction is `724c0bcaf7f4ee252b45962261fdcd81f178ab9d`.
Hugging Face is running `84763a87c7eb5e899d556a57a82145b3acd40b6e`, from approved
GitHub commit `177a6f74572e86978d6d231aeaee8d910a5b95b4`. All 29 uploaded files
matched the approved commit; unrelated Space files and durable dataset revisions
were unchanged. The [post-deployment check](https://github.com/cyborg-nomade/spotify-manager/actions/runs/36130409488)
confirmed authentication, shared state, all four library artifacts, and no active
jobs across 20 routine endpoints before the merge.

## Scope and ownership

The new [`spotify_manager/domain`](../../spotify_manager/domain) package owns
pure decisions over observed facts. It imports only standard-library value
utilities and the existing `unidecode` text-normalization dependency. It does not
construct clients, read configuration or files, prompt, access the network, or
own persistence. All functions receive their dates, timestamps, and observations
explicitly. [Project coding fundamentals](../../AGENTS.md) apply throughout.

| Policy | Domain owner | Existing callers wired through it |
| --- | --- | --- |
| Album keep/remove decisions | `albums.py`: immutable `AlbumAssessment`, typed decision, floor threshold and ratio | Local and live `library_lookups` evaluations; the existing threshold facade remains available to other routines. |
| Release identity and ordering | `releases.py`: edition stripping, non-studio exclusions, distinct studio/review date keys, edition preference | Slow Listening's shared discography helpers and New Kids chronology; existing helper names/constants remain compatibility facades. |
| Primary-artist filtering and track progression | `progression.py`: primary-credit filtering, trailing-unliked count, streak transition, first liked successor | New Kids/Queue 2 and New Wine retain their existing read and checkpoint boundaries. |
| Scrobble completion | `completion.py`: release-tier minimum and distinct played/liked title comparison | New Kids retains its tolerant title/credit parsing and current-year index before invoking the pure rule. |
| Artist promotion | `artists.py`: immutable observed facts and typed ordered reasons | New Kids returns the same display strings through its existing facade. |
| Historical selection | `history.py`: normalized values, eligible dates, track-page/direction rules, album ranking and wrapped rank | Blast from the Past and Palace of Memory retain their existing I/O and random-source acquisition. |

Existing `Scrobble`, `ScrobbleSelection`, and `HistoricalAlbum` names re-export the
same immutable value layouts from the domain. Their field names and serialized
shapes are unchanged. Pydantic response models, API schemas, CLI interfaces,
state documents, prompt text, and effect ordering remain at their existing
boundaries. Two small structural track views describe already-parsed identifiers
and primary credits, allowing policies to retain the original track objects
without importing SDK or routine models.

This item establishes the policy layer. It does not introduce integration ports,
application composition, async execution, or a workflow framework; those remain
items 4–9. Large legacy workflow bodies remain in their assigned migration waves.
Their edits here replace only the extracted decision blocks with policy calls.
Raw Spotify payload tolerance remains in the existing boundary parsers.

## Differences deliberately preserved

- Album retention floors the threshold: one like on three tracks qualifies at
  50%. Empty albums still require one like; nonpositive thresholds and out-of-range
  counts keep their existing semantics. NaN/infinity retain numeric errors.
- Studio chronology fills missing month/day with the beginning of the period and
  sends invalid calendar dates last. Review chronology fills missing month/day
  with the end of the period and accepts numeric calendar-invalid components.
- Saved editions outrank unsaved plain editions. Remaining ties keep decoration,
  track count, date, case-folded name, and identifier ordering.
- Primary-credit filtering preserves order, duplicates, and object identity.
  Progression stops consulting statuses at the first qualifying liked track.
  Canonical endpoints are still applied before successor selection.
- Release completion counts distinct normalized titles, requires all liked titles,
  and retains the studio minimum versus single-track fallback distinction.
- Promotion reasons remain independent and ordered. Existing zero-like routing
  overrides stay in the workflow; saved-release observations can still produce
  promotion reasons for an artist with no liked tracks.
- Historical track selection uses minute digits, an afternoon seventh-page
  exception, direction, and wrapped seconds. Palace album selection uses seconds
  only. Album ranking retains first-seen spelling and its original tie breakers.

## Verification and review

Run the independent policy gate:

```console
just test-domain
```

It runs Ruff, strict mypy, and **122 tests with 100% statement and branch coverage**
of the domain (194 statements, 54 branches). `--confcutdir=tests/domain` excludes
application fixtures. A fresh-interpreter check and import allowlist guard the
inward dependency boundary. Decision tables cover malformed/partial dates,
empty albums/history, promotion thresholds, liked-tail ordering, duplicate
credits/titles, and missing observations.

The existing full randomized suite and all **129 frozen workflow traces** remain
part of the gate. Their JSON expectations were not changed. The deliberate
ceil-threshold regression now patches the domain rule that owns the calculation;
its expected behavior remains the original fixture. Tests also verify that the
interface comparison rejects changed methods, paths, payloads, SDK calls,
reference counts, and schemas.

Source moves necessarily change source inventories and line references. Keep the
item 1 baseline intact, capture to a separate directory, and compare contracts:

```console
.venv/bin/python docs/refactor/capture_baseline.py --write --output /tmp/spotify-interface-review
.venv/bin/python docs/refactor/check_interfaces.py /tmp/spotify-interface-review
```

The comparison checks **ten public artifacts byte-for-byte**, plus the Spotify
endpoint inventory with source line numbers removed. It retains source paths,
call expressions, payloads, methods, SDK implementations/versions, and reference
counts. The two source/dependency reports remain historical evidence. The
original `capture_baseline.py --check` still reports these expected source moves;
no snapshot is rewritten to make it pass.

## Local review

The final globally randomized run passed **1,440 tests** (seed `20260926`).
Application coverage is **90.51% statements** (16,556 / 18,292) and **75.08%
branches** (3,853 / 5,132), versus item 2's 90.38% and 74.84%. Branch measurement
remains diagnostic for the full legacy application; the independent domain gate
requires 100%. Ruff lint/format and mypy pass for all application modules and the
new tests/tooling, with strict mypy applied to the domain and its tests. The
existing Starlette/TestClient deprecation warning remains.

Starting with this item, the review handoff includes a running local web app:

```console
.venv/bin/uvicorn spotify_manager.web:app --host 127.0.0.1 --port 8765
```

The app uses the configured Spotify credentials and shared state/data backends,
just like the normal local environment. Suggested checks are live album
evaluation, a Requeue for a Dream preview, release ordering in Slow Listening,
and historical selections. Existing routine-specific preview effects still
apply; the extraction does not make every dry run side-effect-free.

Approve the PR after automated evidence and local behavior are satisfactory.
Deployment, verification, merge, and cleanup then follow the approved workflow.
