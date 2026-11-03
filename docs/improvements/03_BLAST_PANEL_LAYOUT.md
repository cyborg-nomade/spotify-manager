# Item 3: separate the Blast panel controls

**Status:** implemented, verified, and owner-approved on 2026-11-03.
**Release record:** [PR #75](https://github.com/cyborg-nomade/spotify-manager/pull/75)
records deployment verification, merge, and cleanup.
**Branch:** `codex/improvements-03-blast-panel-layout`.
**Roadmap:** [Item 3](../IMPROVEMENTS_ROADMAP.md#item-3-improve-the-blast-from-the-past-panel-layout).

## Layout and scope

The Blast from the Past panel has three explicit control rows below its heading:

1. Count / Cap and the corresponding numeric input.
2. The main Dry run checkbox, shared terminal toggle, Run, and cancellation.
3. The separate Artists Dry run checkbox, Artists, and its cancellation.

The existing shared progress area remains below those rows. Mobile input labels
retain their accessible associations and existing compact presentation. Desktop
labels can wrap while their numeric fields retain usable widths.

Two small HTML wrappers group the target and main action controls. Scoped CSS
makes each row full-width; it does not use visual ordering to move Artists ahead
of controls that precede it in keyboard navigation. The existing panel enhancer
places its shared log button and command inside the Blast action row when that
row exists; other panels keep their existing strip placement.

All element IDs, action names, request parameters, numeric defaults, dry-run
settings, polling, reconnection, cancellation, and routine behavior are retained.
There are no Python production changes, new dependencies, endpoints, schemas,
state changes, or workflow changes. The existing frontend integration assertion
is adjusted for the command-row host; no unrelated frontend restructuring or
new test framework is included.

## Verification and review

Review used <http://127.0.0.1:8767/?review=item03>.
This temporary server is stopped during release cleanup.
Unlock with `blast-layout-review` (any nonempty text works at loopback).
The preview uses temporary local state/data stores. Both dry-run defaults remain
checked. Review can focus on layout; separate synthetic API transport checks
exercise the controls without account calls.

1. Check Count and Cap at desktop and narrow mobile widths. Their numeric input
   should stay above the main Dry run / Run row.
2. Check that Artists and its independent Dry run remain below Run.
3. Tab through Count, Cap, the visible numeric input, main Dry run, terminal,
   Run, Artists Dry run, and Artists. Visible cancellation controls participate
   immediately after their corresponding action.
4. Open the terminal log; shared progress should remain below all controls.

Browser verification uses synthetic Blast HTTP responses, never live Spotify,
Last.fm, or Random.org requests. It verifies Count, Cap, both dry-run values,
Artists, both cancellation routes, log visibility, and reload reconnecting to an
active job. Responsive measurements cover 320, 375, 390, 760, 980, 1120, and 1440
pixel viewports in Count and Cap modes, including visible active cancellation.
They require zero horizontal overflow, controls inside the card, and target
above Run above Artists. Other panels retain their terminal/command placement.

Completed gates:

- `just ci-test`: **11,847 passed**, seed `975322`, 438.74 seconds; the existing
  Starlette TestClient deprecation warning remains. Ruff, formatting, package and
  strict typing, architecture guards, and independent coverage gates pass.
- All **11 frozen public artifacts** match without baseline changes.
- `just verify-wheel`: **689 packaged files**, imports, **44 commands**,
  **126 wrapped routes**, and both entry points pass.
- Responsive browser measurements passed all 14 Count/Cap viewport combinations
  and seven active Cap/cancellation combinations. All visible active controls fit
  inside the card; the target, Run, and Artists rows stay separated.
- Native keyboard navigation reaches Run after Count, Cap, the numeric input,
  main Dry run, and the terminal toggle, before the Artists controls.
- Captured browser requests retain `count=7&dry_run=true`,
  `max_playlist_length=42&dry_run=false`, the independent Artists dry-run value,
  and both existing cancellation routes. Shared logging and reload reconnection
  work. Other 15 panels retain their terminal/command placement.
- Both isolated servers pass health/authentication, four-source availability,
  and 20 idle-job checks. The review HTML matches this branch exactly.
- Development checks made no live Spotify, Last.fm, or Random.org requests.

## Release and rollback

The owner approved PR #75. Deploy only the changed
`spotify_manager/frontend/index.html` from the approved commit to Hugging Face,
using the active-job and independent state/data safeguards in [DEPLOY.md](../../DEPLOY.md).
No operational files or secrets belong in the code upload.

Verify the running revision, served HTML identity, authentication, shared source
metadata, and idle/reconnection endpoints before merge. Existing synthetic and
local browser checks establish control placement and request compatibility;
production playlist mutations are not needed to verify a layout release.

After merge, stop the owned idle review server, remove the item branch, and
return to clean, current master while preserving unrelated files and review data.
Rollback restores the prior HTML asset; no data or state rollback is required.
