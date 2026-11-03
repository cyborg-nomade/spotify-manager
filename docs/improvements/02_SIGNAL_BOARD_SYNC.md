# Item 2: align Last.fm and Spotify sync modes

**Status:** implemented and verified; awaiting owner PR review before deployment.
**Branch:** `codex/improvements-02-signal-board-sync`.
**Roadmap:** [Item 2](../IMPROVEMENTS_ROADMAP.md#item-2-align-the-signal-board-and-nightly-refresh-modes).

## Behavior

The Data Signal Board replaces Last.fm's dry-run checkbox with Recent / Full,
using the same visual controls as the Spotify mirrors. Recent is the default.
Sync sends `dry_run=false` and the chosen `full_rebuild` value to the existing
history endpoint. Recent merges newer scrobbles; Full replaces history from the
complete live API range through the existing backup and publication stages.
The CLI/API preview options and their defaults remain available.

An active history job locks both mode controls, exposes Stop, and restores its
actual `history_full_rebuild` selection after reload or conflict reconnection.
Cancellation uses the existing endpoint and retains the established persistence
boundaries. Reconnecting to an API-started preview still labels it as Dry run;
the board does not change the running job's options.

The nightly workflow already included Last.fm before albums, tracks, and artists.
Its manifest now requests Full history whenever the workflow selects Full for
Spotify. This replaces the separate monthly Last.fm selection:

| Run | Last.fm | Spotify |
| --- | --- | --- |
| Primary Monday-Saturday, 00:17 Berlin | Recent | Recent |
| Primary Sunday, 00:37 Berlin | Full | Full |
| Manual Recent dispatch | Recent | Recent |
| Manual Full dispatch | Full | Full |
| January 1 override | Full | Selected mode |

The early probes and their cron/timezone declarations are unchanged. Probes
outside 22:00-05:00 Berlin start nothing. Delayed accepted probes retain the
workflow's explicit mode rather than choosing it from the eventual weekday.
The existing maintenance deadline, compatible-job reconnection, all-artifact
freshness shortcut, serial ordering, and restart behavior remain unchanged.
January 1 retains its explicit bypass of generic freshness checks. A completed
unchanged history check is successful and does not stop the remaining jobs;
missing/stale artifact metadata does not qualify as a fresh duplicate.

## Architecture and intentional contract changes

- Frontend actions use the existing history API and shared mode-control helper.
  No frontend source restructuring is included.
- `refresh_jobs` directly builds the selected four-job manifest. The calendar
  domain rule now selects only the annual history override; weekly Full mode
  comes from the workflow flag, including delayed early probes.
- No new endpoints, dependencies, execution callbacks, state namespaces,
  checkpoint formats, or canonical artifact schemas are introduced.
- Intentional changes: the board no longer offers a dry-run control; Full
  workflow requests include history; first-Sunday-only history selection is
  removed. Unrelated routine and API/CLI contracts remain intact.

## Verification and review

Use the isolated preview at <http://127.0.0.1:8767/?review=item02>; unlock with
`signal-board-review`. Its state and canonical data stores are temporary local
copies. Last.fm Sync performs account reads and writes only to the isolated
canonical store; it does not mutate Spotify playlists.

1. Check that Last.fm defaults to Recent and has no dry-run checkbox.
2. Select Full, then Recent; compare the controls with the other files at desktop
   and narrow mobile widths.
3. Run the desired mode and inspect its progress log, counts, and backup path.
4. Reload during a run: the selected running mode and cancellation control should
   return, and mode changes should be disabled until completion or cancellation.
5. Cancel during a read; verify that it stops and the controls become usable.

Automated verification covers manifest selections, annual/DST/window boundaries,
unchanged completed jobs, stale Last.fm metadata, compatible reconnection,
deadlines, and existing CLI/API preview behavior. Browser tests use synthetic
Last.fm responses and isolated data to verify requests, controls, reload, and
cancellation without live account reads.

Completed gates:

- `just ci-test`: **11,847 passed**, randomized seed `676736`, 434.88 seconds;
  the existing Starlette TestClient deprecation warning remains. Ruff, formatting,
  package/strict typing, architecture guards, and independent coverage gates pass.
- All **11 frozen public artifacts** match without baseline edits.
- `just verify-wheel`: **689 packaged files**, imports, **44 commands**,
  **126 wrapped routes**, and both entry points pass.
- New dispatch tests pass strict typing and verify the real automation entry
  point's complete ordered API requests across calendar and workflow selections.
- Desktop and mobile browser checks verify both API parameter selections,
  cancellation, reload restoring Full and locking modes, and real local
  publication. Recent retained the stored play and merged another; Full replaced
  the two-play history with the single live play and set `full_rebuilt_at`.
- Mobile viewport verification found no horizontal overflow. Both isolated
  servers pass health/authentication, four-source availability, and 20 idle-job
  checks. The real-account review preview matches all changed runtime files.
- No production refresh or workflow dispatch was started during implementation.

## Release and rollback

Wait for owner approval before deployment or merge. Deploy the explicit changed
application files to Hugging Face with active-job and shared-artifact safeguards
from [DEPLOY.md](../../DEPLOY.md). No operational data or secrets belong in the
code upload. Verify runtime identity, authentication, source metadata, and job
reconnection before merging the workflow change.

After merge, run the workflow's read-only `check_only` dispatch from master and
record its result. The selected API parameters and all four sequential jobs are
covered by offline dispatch tests. The owner may perform live Recent/Full checks;
do not run an expensive history rebuild merely to test a workflow label.

Code rollback restores the prior board and mode-selection rules. Existing valid
publications remain valid; use normal reviewed backups for any data restoration.
