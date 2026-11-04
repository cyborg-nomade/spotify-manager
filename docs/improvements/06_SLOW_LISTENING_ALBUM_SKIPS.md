# Item 6: skip proposed albums in Slow Listening

**Status:** implemented and verified; owner PR approval pending.
**Branch:** `codex/item06-slow-listening-album-skips`.
**Roadmap:** [Item 6](../IMPROVEMENTS_ROADMAP.md#item-6-skip-proposed-next-albums-in-slow-listening).

## Behavior

At a proposed next studio album or EP, web and CLI now offer:

- **Accept album:** choose the displayed playable track as the next marker.
- **Skip track:** retain the existing individual-track rejection behavior.
- **Skip album:** reject the whole proposed edition and propose its successor.
- **Pause:** keep the current marker and resume this run later.

Accepting an album adds one marker, as Slow Listening already does. Repeated
album skips do not require rejecting its tracks individually. The new action is
available only for proposed releases beyond the current mapped studio edition.
It cannot abandon the album currently in progress, including when the playlist
marker belongs to an alternate edition of that same album.

Within-album Add track / Skip track / Quit behavior remains unchanged. Existing
studio/EP eligibility, preferred-edition selection, equal-date release ordering,
two-marker limit, first playable track order and append-before-remove safeguards
remain in place. Skipped editions bypass their track reads when a run resumes.
The original empty-successor outcome still leaves the source unchanged rather
than inventing a playable marker.

Exhausting all remaining proposed albums retains the existing artist-completion
policy: a live run removes the source and asks for completion acknowledgement;
dry run previews completion without either effect. The result lists rejected
album names separately from individually rejected track candidates.

## State and recovery

Each active entry gains an optional `skipped_albums` mapping of edition ID to
display name. An album rejection checkpoints the full namespace before another
album is proposed. Pause, cancellation, a checkpoint response failure and process
restart therefore honor the last accepted checkpoint. Rejected checkpoints cause
the affected album to be offered again; accepted checkpoints prevent replay.

The accepted transition plan retains the album labels before appending anything.
Restart after an accepted append finishes that saved transition without another
album prompt or duplicate append. Old entries without the mapping and already
saved plans remain readable. Malformed new mappings raise a state error instead
of silently discarding decisions. Namespace version 1 and existing unrelated
fields remain unchanged; no backfill or operational-data migration is needed.

Dry run starts a fresh detached plan, uses the same choices, and suppresses
Spotify and namespace writes. It retains the existing local audit behavior.
Pausing a preview explicitly says that preview decisions were not saved.
Live-mode cancellation retains already checkpointed rejections for the next run.
Rejections belong to the current source entry/run, rather than a global artist
preference.

## Architecture and wire contract

`TrackSelection` retains the chronological scan and original track interaction.
It calls the named `AlbumSelection` stage only for a proposed later edition.
That stage owns validation and checkpointing through an explicit
`ReleaseActionReader` and the existing namespace checkpoint resource. Bootstrap
composes the web/CLI resources; clients remain outside business execution. There
are no function-shaped execution dependencies, new packages or workflow engine.

The existing choice endpoint remains
`POST /commands/flush-slow-listening-jobs/{job_id}/choice`. Additive contracts are:

- pending choice kind `release`, with the proposed release metadata in the
  existing `releases` collection;
- `skip_album`, accepted only for a proposed-release interaction;
- optional `request_id` in pending choices and submissions; and
- `skipped_albums` in result/audit records, empty for original track-only results.

Each prompt, including track, tie ordering and completion, receives a fresh token.
The browser submits the rendered token; stale tokens receive 409 and unavailable
actions receive 400. Existing API clients may omit the token for compatibility.
Choice/cancellation consumption retains the existing job lock and cancellation
precedence. Polling preserves the DOM for the same request, retaining keyboard
focus and edited tie-order controls. Reload restores the current prompt and its
preview/live mode; the mode checkbox is locked while a job is active.

Noninteractive Python callers retain the original track-choice path unless they
opt into the new operation's release reader. A compatibility reader resuming an
entry with album rejections still honors those persisted decisions before asking
its original track questions.

The 16 frozen Slow Listening traces gain only the empty `skipped_albums` result
field. A separate capture was compared after removing that one field from
recognized flush results: all pre-existing observations, values and effect order
are identical. No other routine traces changed. Only the additive OpenAPI models
change in the public baseline; routes, CLI commands and Spotify calls are stable.

## Owner review

Account preview: <http://127.0.0.1:8767/?review=item06>.
Offline demo: <http://127.0.0.1:8769/?review=item06>.
Unlock text: `album-skip-review` (any nonempty value works on loopback).
Both use isolated working files and local state/data stores. Keep Dry run checked
when using your account. The offline demo uses the real application and HTTP
workers with synthetic Spotify metadata/effects, and makes no live service calls.
Its Spotify links identify synthetic releases. Other routines are outside that
fixture's scope.

1. In the offline demo, run Slow Listening with Dry run checked. Skip the second
   and third albums, then accept the fourth. The preview should show both skipped
   albums and one proposed marker.
2. Run another preview and skip all three remaining albums. Check the explicit
   exhaustion reason and proposed artist completion.
3. To test persistence, use the offline demo with Dry run unchecked. Skip one
   album and pause at its successor. Rerun with Dry run still unchecked; the
   rejected album should not be offered again. Accepting a marker changes only
   the simulated playlist.
4. After accepting a marker, start a preview inside that album. Its original
   track controls should appear, with no Skip album action.
5. Reload at an album prompt. Its request identity and mode should return. Tab
   between controls and verify polling does not move focus. Cancellation should
   clear the pending prompt while retaining accepted live checkpoints.

## Verification and release

Verification completed on the review branch:

- `just ci-test`: **12,043 passed**, random-order seed **36847**. Package and strict
  inner-layer typing, Ruff, architecture guards and independent coverage gates
  passed. Aggregate coverage is 95.33%; the package and domain/application
  statement/branch floors remain satisfied.
- **132 focused tests** passed for multiple skips, individual-track rejection,
  exhaustion, pause/cancel recovery, checkpoint failures, append interruption,
  alternate source editions, malformed state, equal-date ordering, stale requests,
  CLI/web execution and dry-run mutation suppression.
- The **16** frozen traces retain every previous observation after removing only
  the additive empty result field. All **11** public baseline artifacts passed;
  only OpenAPI changed. Wheel verification matched **702** packaged Python and
  frontend files, **44** commands and **134** wrapped routes.
- Browser checks covered repeated skips and acceptance, exhaustion, reload,
  keyboard focus through polling, equal-date ordering through polling, live-mode
  pause and process restart, and original within-album controls. The accepted
  namespace bytes survived restart unchanged. Controls fit at **320**, **390** and
  **1120** px widths; the temporary viewport override was reset afterward.
- Both isolated review runtimes match all **702** packaged source/frontend files,
  return healthy responses, expose the new contract and have **20** idle job-list
  endpoints. The offline catalog was reset to its default review configuration.

Deployment and merge require this item's approval under
[AGENTS.md](../../AGENTS.md). Deploy only approved runtime files, preserving
credentials, operational files and independent state/data publications. Verify
active jobs before deployment, then runtime identity, health, served frontend,
authentication and shared artifacts before merge.

Rollback restores prior runtime/frontend without reverting unrelated data. An
older runtime does not understand unplanned active entries with album rejections;
finish those runs first or retain a namespace backup and explicitly resolve them
before resuming on older code. Existing accepted transition plans remain usable.
Stop the owned idle review servers and remove the item branch during cleanup.
