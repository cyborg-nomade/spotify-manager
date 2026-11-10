# Second routine improvements: final verification and conclusion

**Completed:** 2026-11-10.

All five items in the [approved second roadmap](../IMPROVEMENTS_ROADMAP_2.md)
are implemented, owner-reviewed, approved, deployed and verified. This closes the
follow-up plan approved on 2026-11-09. The earlier [improvements](../improvements/FINAL_VERIFICATION.md)
and [backend refactor](../refactor/FINAL_VERIFICATION.md) remain separately complete.

## Delivered behavior

| Item | Delivered result | Release |
| --- | --- | --- |
| 1 | New Kids planning catalogues sort oldest first, alphabetically on equal dates, preserving selected listening order and current release identity. | [#85](https://github.com/cyborg-nomade/spotify-manager/pull/85) |
| 2 | The Last.fm panel downloads the latest complete stored history through an authenticated, integrity-checked attachment endpoint. | [#86](https://github.com/cyborg-nomade/spotify-manager/pull/86) |
| 3 | The Data Signal Board sits immediately below New Year's Routines on desktop, tablet and mobile. | [#87](https://github.com/cyborg-nomade/spotify-manager/pull/87) |
| 4 | Flush Mode has shared hysteresis, persistent Automatic/Force On/Force Off controls and backend admission enforcement. New Wine uses recovery first, allowing discovery only for capacity recovery cannot fill. | [#88](https://github.com/cyborg-nomade/spotify-manager/pull/88) |
| 5 | Nightly maintenance checks Flush Mode even when library artifacts are already current. Failures retain observations and retry within the deadline; overrides persist. Check-only stays read-only. | [#89](https://github.com/cyborg-nomade/spotify-manager/pull/89) |

Each roadmap item links its implementation guide, intended contract changes,
verification and release evidence. The final [nightly guide](05_NIGHTLY_FLUSH_MODE.md)
records the operational options and actual live verification.

## Architecture and verification

The modular monolith, native async execution, direct named application stages,
pure domain decisions, typed resources and bootstrap-owned construction remain.
Readability, callback-dependency, import-direction and lifecycle guards passed.
No new package, service, secret or workflow framework was introduced. Frontend
source restructuring remains outside this completed roadmap.

The final local quality run passed **12,593 tests**, seed **227521**, in **492.72
seconds**, with **95.41%** aggregate coverage and all independent statement/branch
floors passing. Package typing checked 744 files; strict inner typing checked
493 files. Ruff, formatting, architecture and public-interface gates passed.
All **11 public artifacts** remain unchanged in the final item. Wheel checks
verified **744 exact runtime files**, **45 commands**, **139 wrapped routes** and
both installed entry points. The automation script remains standard-library-only
and compatible with the configured Python 3.13 Actions runner.

Real HTTP/persistence integration tests cover Automatic, Force On and Force Off
across normal counts, activation, hysteresis, failure retention, retry and exit,
while all four canonical artifacts are already current. Entry-point tests cover
Recent/Full/annual modes, repeated triggers, DST, maintenance boundaries and
read-only versus live verification. All 90 prior recorded automation outcomes
and complete existing request/message sequences are retained after removing only
the new policy observations; 31 scenarios intentionally extend that contract.

Offline execution of the real script and browser polling demonstrated activation,
override preservation, stale status and automatic recovery. Check-only left
state, the count sequence and durable publications byte-for-byte unchanged.
The synthetic fixture was reset after verification. Earlier item guides retain
responsive layout, download integrity and recovery/interaction evidence.

## Final release

The final owner-approved source is
[`ea31362`](https://github.com/cyborg-nomade/spotify-manager/commit/ea313620e6756a9277454e50a38b18913e6d2f3c),
based on Item 4 merge `61147ad`.
[CI 42679506425](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42679506425)
passed all **12,593 tests**, seed **663027**, in **793.21 seconds**, with independent
coverage floors, typing, architecture, interface and packaging checks passing.

Space revision `749d14d824350497dd10cb2842e08b8318aca122` is running. Only the
**three approved automation helper files** were uploaded, with exact prior Space
and blob guards. All **186 cumulative release blobs**, runtime identity, exact
served frontend, health and authentication were verified. Deployment left state
at `78be6ea4e6f3cdae24cf866ceac01db3ec636523` and canonical data at
`de774b845146f76ea403beca7c77ac5049489c9e` unchanged.

Authenticated [preflight 42781756999](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42781756999)
and [read-only postflight 42781911517](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42781911517)
confirmed all four sources, shared state and **20 idle routine endpoints**.
Postflight read policy status without checking Spotify counts.

The approved [live Flush Mode-only run 42782100348](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42782100348)
completed successfully without library jobs. Counts were **4,795 / 1,133**;
Automatic correctly retained active mode. Only the policy namespace observations
changed, at state revision `03d5517b32290fa09f5ff61693c992debbb6d9eb`.
Immutable snapshot comparison confirmed that operator control, every unrelated
namespace and canonical data were preserved.

Release tracking and this conclusion are documentation only; the approved source
above remains the runtime authority. Review servers are retired, with local files,
operator state, private evidence and all existing stashes retained.

## Operational handoff

Automatic activates when The Queue reaches 2,400 tracks or Queue 2 reaches 1,200.
It exits only when both are at or below 1,200 and 900. Force On/Off persists until
the operator returns to Automatic; nightly observations still update underneath
an override. Failures retain the prior successful counts and decision.

Nightly Recent/Full schedules, Berlin maintenance windows, DST handling, workflow
concurrency, library job recovery and credentials remain unchanged. Each admitted
maintenance run checks policy before artifact freshness; outside-window probes
start nothing. Use `check_only` for read-only deployment verification and
`flush_mode_only` for a live policy check without library jobs. The existing panel
also provides Check now and manual overrides.

Active mode blocks new Found Art, Genre Reveal, Queue/Queue 2/Queue 3 and Sauvignon
starts, including dry runs, queue flushes and resumptions. Already-admitted jobs
finish normally. The owner operates backlog flushing manually outside the app.
New Wine starts with No Discovery but may use normal Wine Cellar transfers to
fill remaining capacity below ten tracks, preserving explicit skips and pauses.

Rollback preserves shared policy, manual overrides, accepted plans, checkpoints
and canonical artifacts. Restoring pre-Flush runtime removes policy enforcement;
restoring only the prior automation code stops nightly checks but retains the
released panel and manual controls. See [DEPLOY.md](../../DEPLOY.md) and each
item's rollback guidance. No work remains in this roadmap.
