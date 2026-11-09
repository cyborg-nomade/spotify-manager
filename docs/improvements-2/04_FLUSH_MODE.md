# Round 2, item 4: Flush Mode policy and panel

**Status:** implemented and verified; owner review pending.
**Branch:** `codex/round2-item4-flush-mode`.
**Roadmap:** [second-round item 4](../IMPROVEMENTS_ROADMAP_2.md#item-4-flush-mode-policy-shared-state-and-panel).

## Policy and controls

Flush Mode has a full-width panel immediately below the Data Signal Board. It
shows effective mode, Automatic/Force On/Force Off selection, both queue counts,
last successful check and an explicit failure notice for stale observations.

| Playlist | Automatic activation | Required for automatic exit |
| --- | ---: | ---: |
| The Queue | At least 2,400 items | At most 1,200 items |
| Queue 2 | At least 1,200 items | At most 900 items |

Either activation threshold turns automatic mode on. Once active, both exit
conditions must hold to return to normal. Counts between those edges retain the
previous automatic decision. The automatic decision keeps updating under a
manual override; returning to Automatic selects that latest decision. Force
On/Off persists across checks, reloads and restarts.

Before the first successful check, Automatic is normal and counts are explicitly
unknown. Check now reads only the two live total fields, including unavailable
markers, without traversing playlists or running a listening routine. Status
polling reads shared policy; it does not trigger Spotify reads. Nightly checking
remains separately scoped to roadmap item 5.

Active mode blocks every new start/resumption of Found Art, Genre Reveal, The
Queue, Queue 2, Queue 3 and Sauvignon. This includes dry runs, both queue flushes
and Queue 3's standalone annual import. Already-admitted jobs retain their
settings and may finish, accept choices or cancel normally. Read-only progress
and status remain available. A bookmarked Genre Reveal page also respects mode.

The HTTP job starters call the named application admission check before job
registration. Genre mutation/source endpoints use the same check. The CLI
callback admits restricted commands before canonical-file hydration, routine
configuration or Spotify construction. No policy check is added inside an
already-running worker. Starts fail closed if control state cannot be read.

## New Wine capacity exception

While active, Flush Mode initially forces No Discovery even when the request
passes false. Admission records that force separately from ordinary operator
preferences, so a saved false mode cannot bypass it. Existing saved run settings
otherwise retain their original resume precedence.

The routine first uses the existing Wine Cellar recovery eligibility: at least
18 live liked tracks or three live saved albums, with the existing confirmation
prompt. If that pass finishes below ten tracks, normal transfers from remaining
Wine Cellar artists may fill only the remaining slots. This also applies when
No Discovery was selected manually outside Flush Mode.

The fallback keeps the same transfer session, destination projection, source
membership and skipped-marker set. Accepted recovery candidates precede fallback
candidates; dry runs do not transfer those candidates twice. Quit/pause prevents
fallback. A persisted fallback and accepted pending transfer resume without
re-adding a secured destination marker or discarding an explicit skip.

For example, one qualifying artist followed by nine unfamiliar records can fill
an empty New Wine to ten. If only two source records exist, the result reports
two. An empty Wine Cellar remains empty; no records or full-size counts are
fabricated. Normal completion routing to Sauvignon remains part of New Wine;
the standalone Sauvignon command is still blocked.

Progress and results explain when No Discovery turns off. The refill response
adds `discovery_fallback`; its `no_discovery` describes the completed pass.
`ineligible` retains the count rejected by the initial recovery scan. The locked
checkbox in active Flush Mode continues to govern the next start.

## Persistence and architecture

`domain.flush_mode` owns threshold decisions, effective control, reasons and
field-preserving update models. Named application use cases coordinate checks
and admission. Bootstrap constructs the existing central state and native
Spotify resources; adapters own validation, two count reads and persistence.

The version-1 `flush_mode` namespace stores `control`, `automatic_active`,
`counts`, `checked_at`, `attempted_at` and `error`. Reading absent state returns
defaults without creating a namespace. A new default/schema is registered in the
shared state editor; observations are read-only there and control is selectable.
Other namespaces, accepted plans and canonical data are unchanged.

Count results merge against the latest namespace with guarded central-state
writes. Conflicts reload and reapply only the fields owned by that change. A
check cannot overwrite a concurrent manual override; a control change cannot
discard concurrent observations. Older checks cannot replace newer completed
observations or failures. Failed reads retain the previous successful counts,
timestamp and automatic decision. A successful check clears the failure.

Complete blocking state operations finish on the existing bounded thread bridge,
including cancellation draining. The callback ledger records the two exact
standard-library `to_thread` requirements; no workflow callback is introduced.

The frontend applies admission state to start buttons and preserves active
choices/cancel controls. Versioned responses prevent older polls from undoing a
control selection. Check now leaves the override controls available while its
Spotify reads are pending. Temporary viewport overrides are reset after review.

## Interfaces

```text
GET  /flush-mode
PUT  /flush-mode/control   {"control":"automatic"|"on"|"off"}
POST /flush-mode/check
```

These routes use the deployment's existing authentication. A blocked routine
start returns 409. Unavailable control/persistence returns 503. A failed count
check returns retained state with an explicit `error`, so failure never looks
like a successful fresh observation. Invalid control values return 422.

```console
uv run spotify-manager flush-mode
uv run spotify-manager flush-mode --control on
uv run spotify-manager flush-mode --control off
uv run spotify-manager flush-mode --control automatic --check
```

Status and override-only CLI operations require no Spotify client or library
hydration. No dependency or destructive state/data migration is introduced.

## Owner review

- [Account preview](http://127.0.0.1:8767/?review=round2-item4).
- [Offline demo](http://127.0.0.1:8769/?review=round2-item4).
- Unlock text: `flush-mode-review`.

Both environments isolate local files, policy state and durable publications.
No account routine or live count check is started by the agent. The offline
demo supplies synthetic counts and Wine Cellar markers; its temporary code and
credentials are excluded from the repository and release.

1. In the offline demo, leave Automatic selected and use Check now repeatedly:
   2,399/1,199 stays normal; 2,400/900 activates; 1,300/950 retains active mode;
   the next check fails and retains the decision; 1,200/900 exits. Each pair of
   reads takes a few seconds to expose concurrent controls.
2. Force On/Off while a check is pending. The override persists when counts
   arrive and after reload. Automatic restores the independent automatic result.
3. Force On. All seven protected start buttons are disabled, including Queue
   Fill/Flush. New Wine's No Discovery is checked and locked. Other routines and
   existing job interaction controls retain their ordinary behavior.
4. Keep New Wine in Dry run and run it in the offline demo. Confirm Known Artist
   from Wine Cellar; the nine remaining slots use discovery and the result
   identifies the fallback. Skip preserves the rejected artist. Quit pauses
   without discovery. Force Off also permits testing manually selected No Discovery.
5. Resize to mobile/tablet or use the keyboard. Both full-width panels retain
   their order, and the controls remain usable without horizontal scrolling.

The initial offline scenario is restored after verification for repeatable review.

## Verification and release

Verification includes exact threshold edges and hysteresis, persistent overrides,
real namespace CAS collisions, out-of-order checks, failed reads, restart,
authenticated controls, every protected HTTP/CLI start, active-job completion,
and New Wine's recovery, capacity, skip, pause, preview and resume boundaries.

- `just ci-test`: **12,562 passed**, random-order seed **316971**, 504.14 seconds;
  aggregate coverage **95.40%**, with every independent coverage floor passing.
  The sole warning is the existing Starlette/httpx TestClient deprecation.
- Package Ruff and formatting, package typing (744 checked files), strict inner
  typing (492 checked files), callback and architecture guards passed.
- Wheel verification: 744 exact runtime files, 45 commands, 139 wrapped routes
  and both installed entry points passed. All 11 public contract artifacts match
  after the intended new routes, command, namespace and response field updates.
- Browser checks exercised all five synthetic count outcomes, an override during
  a pending check, restart, unavailable-state blocking, the bookmarked Genre
  Reveal page, and New Wine's recovery acceptance and explicit skip. Both Wine
  previews filled only ten slots and left state and synthetic playlists untouched.
- Widths 320, 390, 760, 1119, 1120 and 1440 retain full-width board/policy placement
  and one row of override choices without horizontal overflow.

The 18 existing cellar traces are intentionally extended for the approved
under-capacity behavior. Every trace retains its exact pre-fallback event prefix;
only the new fallback and its resulting state/effects extend that contract.
Independent capacity and interruption tests verify the new behavior. Unrelated
historical traces and source inventories remain unchanged.
The lifecycle fixture adds only the default false admission-force argument for
New Wine; the existing API result expectation adds the false fallback field.

Deployment and merge await owner approval. After approval, deploy only approved
runtime changes, verify state/data and read-only health first, then validate the
policy controls as agreed. Rollback restores the prior runtime files and removes
the new modules, preserving shared namespaces, accepted transfer intent and
canonical data. Older code does not enforce Flush Mode; retained namespace data
allows re-deployment without losing the operator selection.
