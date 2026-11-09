# Round 2, item 3: Data Signal Board position

**Status:** owner-approved, deployed and verified on 2026-11-09 in
[PR #87](https://github.com/cyborg-nomade/spotify-manager/pull/87).
**Branch:** `codex/round2-item3-signal-board-layout`.
**Roadmap:** [second-round item 3](../IMPROVEMENTS_ROADMAP_2.md#item-3-restore-the-desktop-data-signal-board-position).

## Behavior and implementation

The full-width Data Signal Board now sits directly below New Year's Routines
on desktop as well as tablet and mobile. The desktop grid previously reserved
rows 2–4 for the listening modules, causing the automatically placed board to
appear beneath them despite its earlier source position.

At the existing 1120 px desktop breakpoint, the system card now explicitly
occupies row 2. Recovery, Discovery, Deep Listening and Album Cycles shift down
one row, retaining their existing column spans and relationship to each other.
The smaller layouts continue to use their existing source-based placement.

The runtime change is confined to CSS in `frontend/index.html`. Markup and
JavaScript are byte-for-byte unchanged, preserving source order, action
bindings, polling and keyboard behavior. No Python runtime code, route,
dependency, shared state or data schema changes. Existing layout assertions are
updated for the intended desktop row positions.

## Owner review

- [Account preview](http://127.0.0.1:8767/?review=round2-item3).
- [Offline demo](http://127.0.0.1:8769/?review=round2-item3).
- Unlock text: `signal-board-review`.

Both use isolated local state, files and durable publications. Layout review
requires no routine run. No account routine was started. Preview files,
credentials, fixtures and screenshots remain outside the repository and release.

1. On a desktop viewport of at least 1120 px, confirm New Year's Routines comes
   first, then the full-width Data Signal Board, then the listening modules.
2. Resize to tablet and narrow mobile widths. The board retains the same
   position, readable controls and no horizontal page overflow.
3. Tab from New Year's Run into the board's first Recent control. Last.fm's
   Recent/Full modes still respond to the keyboard; the terminal, Sync and
   Download controls retain their tab order.

## Verification and release

All **55 focused web, interface-contract and authenticated history-download
checks pass**. Runtime Ruff lint/format checks pass for 732 Python files, as do
lint and formatting for the updated existing web test. All **11 public
artifacts** verify unchanged. Wheel verification passes for **734 exact runtime
files**, **44 commands**, **136 wrapped routes** and both entry points.

Browser geometry checks cover **320, 390, 760, 1119, 1120 and 1440 px**, including
both sides of the desktop breakpoint. At every width the board is full-width,
exactly one grid gap below New Year's Routines, with all listening modules
below it. There is no horizontal overflow or overlap between top-level panels.
Keyboard mode selection and tab order work; no console errors were observed.
The temporary viewport override was reset, and a desktop screenshot is retained
privately for review.

Both preview servers are healthy, serve all **734 exact branch runtime files**
and have **20 idle job endpoints**. Read-only preview verification leaves their
local state and publication unchanged. The complete randomized suite and typing
checks also run through the PR's existing GitHub Actions workflow.

The owner approved PR #87 on 2026-11-09.
[Source CI 42598046805](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42598046805)
passed all **12,465 tests**, seed **858415**, in **475.71 seconds**, with independent
statement/branch floors passing. Typing, architecture, lifecycle, interface and
packaging gates passed.

Authenticated [preflight 42622787182](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42622787182)
and [postflight 42623034680](https://github.com/cyborg-nomade/spotify-manager/actions/runs/42623034680)
confirmed shared state, all four canonical artifacts and **20 idle routine
endpoints**. Neither check started a routine.

Only the approved **frontend file** was deployed, with the prior Space revision
and file hash guarded. Space revision `9a9469410601ae11c5c9340e913f4efddbc305cc` is running;
all **170 cumulative runtime blobs**, exact served frontend, runtime identity
and health were verified. Shared state remained at
`ace561202e4d4fd28924b14a4f127f8907029066` and canonical data at
`7275bd794de01e5ab8b541ce6b5535837a7d267a`. The approved runtime source remains
`ef1912a98a68b7a44c586251e8ae09226873f614`; release tracking is documentation only.
Credentials, operator files, preview fixtures and screenshots were excluded.

Rollback restores the prior frontend file without changing shared data or state.
The review processes are retired after idle-job verification; their local files
and private evidence are retained.
