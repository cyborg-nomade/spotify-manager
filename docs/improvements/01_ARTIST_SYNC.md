# Item 1: recover the packaged artist source export

**Status:** source recovery approved and deployed; Recent publication verified.
Automatic cooldown retries requested during Full verification are implemented
and awaiting review before deployment.
**Branch:** `codex/improvements-01-artist-sync`.
**Roadmap:** [routine improvements, Item 1](../IMPROVEMENTS_ROADMAP.md#item-1-restore-reliable-artist-synchronization).

## Failure and cause

The nightly schedule reaches the artists stage. It is not a missing cron trigger:

- [2026-09-25 evening run](https://github.com/cyborg-nomade/spotify-manager/actions/runs/36186217752)
  fails with `Could not read valid JSON from …/YourLibrary.json`.
- The [earlier successful run](https://github.com/cyborg-nomade/spotify-manager/actions/runs/36077978650)
  skipped execution because artifacts were already fresh in that maintenance
  window. Its green conclusion does not establish a new artist publication.
- [2026-11-02](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41377835402)
  and [2026-11-03](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41574982892)
  complete Last.fm, albums, and tracks, then encounter the same artist failure.

The Space repository's export is valid JSON: 12,904,893 bytes with 41,020 artist
candidates. Read-only inspection of the deployed image at Space revision
`3d71ef63e020bc10cae221dbffd680c9cf39ab04`, image tag
`cpu-3d71ef6-i1oqff0m`, confirms that the image instead packages this 133-byte file:

```text
version https://git-lfs.github.com/spec/v1
oid sha256:e72da31d70022ae8e11ab5a6425181d86b82d3e484fa1db9ce4477d4b7400552
size 12904893
```

Recent refreshes read the export as a candidate source before follow-status
verification. Full refreshes use it if the bounded cursor scan needs fallback.
Both paths pass the pointer text to the JSON decoder and stop before publication.
The published source and the local committed export have the pointer's exact
digest. This diagnosis does not assume every historical failed run has this cause.

## Change and execution path

The existing application stages and listening rules remain unchanged:

```text
HTTP/CLI feature → named analysis operation → artist preparation
    → AsyncAnalysisStorage.export_artists → AnalysisStorage.export
    → SpaceLibraryExport.recover → Hub source download and integrity checks
    → existing candidate verification → backup and canonical publication
```

Bootstrap supplies a named recovery resource only when `SPACE_ID` is present.
It uses the existing data-token, state-token, and `HF_TOKEN` precedence. The
credential needs read access to the owning private Space, in addition to the
existing dataset permissions. Tokens are omitted from resource representations.

Recovery accepts only a complete Git LFS pointer at the configured packaged
`YourLibrary.json` path. It downloads that Space's source through the existing
Hub SDK, checks byte length and SHA-256 against the pointer, and validates the
export schema. A newer, different export cannot silently replace the packaged
source. Ordinary malformed JSON, malformed pointers, custom source paths, and
invalid schemas retain explicit failures.

The download remains in the SDK cache; neither the packaged source nor a user
export is rewritten. Local execution without `SPACE_ID` remains offline. Blocking
work stays within the existing awaited analysis-file operation and capacity limit.
There are no new dependencies, public routes, callbacks, state namespaces, or
checkpoint formats. Existing recent retention and full follow-verification rules,
backups, and durable publication are preserved.

## Automatic cooldown retries

The owner approved the source-recovery PR, which was deployed at Space revision
`26307167687ade343447dda44ff9137a91f51790`. The
[completed Recent recovery](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41612309485)
published 37,910 artists (+24) at `2026-11-03T09:38:40.506387Z`.
The owner's subsequent Full test resumed correctly from checkpoints, but repeated
Spotify rate limits required repeated manual restarts. On 2026-11-03 the owner
requested automatic retries for these pauses. Full publication remains unverified.

This extension deliberately changes the previous terminal 429 pause behavior for
library analysis and Spotify mirror refreshes, in web, CLI, and scheduled runs:

- `LibraryAttemptPolicy` handles rate limits separately from transient failures.
  It retries the same request after the parsed cooldown, without consuming the
  server/connection failure budget or restarting accepted scan pages.
- The domain delay rule honors long reported cooldowns without the transient
  delay cap. Missing or invalid deadlines use exponential backoff from 60 to
  900 seconds; zero deadlines wait at least one second to avoid busy retries.
- `LibraryRetry` records `rate_limit_retry_scheduled` and uses the existing
  named wait resource. The HTTP worker exposes `waiting`, an automatic-retry
  explanation, and `retry_at`; its existing cancellation signal interrupts waits.
- Browser reload reconnects to the waiting job. Closing a browser does not stop
  the server job. A Space restart still requires restarting the sync to resume
  its checkpoint; this change does not introduce a persistent job scheduler.
- Actions already treats `waiting` as active, polls until completion, and
  cancels at its maintenance deadline. No workflow schedule changes are needed.

Spotify documents its cooldown in seconds in the 429 response's `Retry-After`
header: [rate-limit guidance](https://developer.spotify.com/documentation/web-api/concepts/rate-limits).
Other routines' rate-limit behavior is outside this extension.

## Verification

- Exact-pointer proof: the new resource resolved the pointer extracted from the
  deployed image, checked the original digest, and recovered all 41,020 artist
  candidates in a temporary local workspace. Production was read only.
- Focused infrastructure tests cover local reads, pointer decoding, path scope,
  credential precedence, download/read failures, size/digest mismatches, schema
  validation, and unchanged source bytes.
- Complete routine tests cover recent retention, full removal of unfollowed
  candidates, real local durable publication, failed-source preservation,
  cancellation after candidate preparation, restart without rereading the export,
  and rejection of incomplete follow-status responses.
- Existing analysis sequence and recovery checks pass, including frozen ordered
  effect traces. With automatic retries, `just ci-test` passes: **11,835 tests**,
  randomized seed `501474`, in 441.74 seconds, with the existing Starlette
  TestClient deprecation warning.
  Ruff, formatting, package typing, strict business/native-adapter typing, and
  independent statement/branch coverage gates pass.
- Cooldown regressions cover repeated limits beyond the transient attempt bound,
  long deadlines, missing/malformed headers, interruptible waits, recent/full
  durable publication, cancellation without publication, and checkpoint resumption.
  Package coverage is 95.71% statements / 92.17% branches; domain and application
  each retain 100% statement and branch coverage.
- All 11 frozen CLI/API/frontend artifacts match without baseline changes.
- `just verify-wheel` passes: 689 packaged Python/frontend files match source;
  imports, 44 commands, 126 wrapped routes, and both entry points pass.
- Local preview health, password enforcement, state/source reads, and all 20
  empty active-job/reconnect routes pass. No routine was started during that smoke.
- A separate browser demo with synthetic Spotify responses completed after
  consecutive 30-second and 4-second cooldowns. Reload reconnected to the waiting
  job; cancelling a wait stopped promptly, and restarting resumed its checkpoint.
  The demo used temporary local data and made no live Spotify calls.

## Operator review

Preview: <http://127.0.0.1:8768/>. Unlock with `artist-sync-review`.

The server uses a private temporary copy of this branch, local state/data stores,
copied OAuth caches, and the exact deployed export pointer. Canonical review
files and publications stay in that temporary workspace. Spotify reads still use
the configured account and its existing rate limits.

1. In the Data Signal Board, run the artists Recent sync and inspect its log.
2. Verify the old export JSON error is absent. Successful completion should
   update the isolated artist source metadata.
3. Run Full if the Spotify credentials permit it. During a rate limit, verify
   the job shows `waiting` with an automatic-retry explanation and deadline,
   then resumes automatically. Repeated limits should schedule another wait.
4. Cancel and restart a waiting refresh if desired; accepted candidates should
   resume through the existing checkpoint mechanism.

## Release and rollback

The source-recovery changes have approval and are deployed. The new automatic
retry extension requires review before deployment. Preserve shared state/data
revisions and active job safeguards from [DEPLOY.md](../../DEPLOY.md).
Deploy only the changed bootstrap
and storage modules plus the new source-recovery module, analysis domain rules
and values, library retry resource, and analysis HTTP worker. Keep operational data
and the packaged source out of the deployment overlay.

After deployment, verify code identity, health/authentication, inactive-job
endpoints, and unchanged shared artifacts before beginning recovery. Verify an
artists Recent refresh and a Full refresh, recording any genuine Spotify throttle
or maintenance-window pause separately from completed publication. Check the
durable artists metadata and resulting validated contents before merging.

No schema migration is required. Rolling back only the cooldown extension restores
the previous terminal rate-limit pauses. Full Item 1 code rollback reverts its
seven runtime modules.
An already accepted artist refresh is valid data and is not automatically undone
with a code rollback; use its normal reviewed resource backup if data restoration
is necessary. The source-download cache is disposable.
