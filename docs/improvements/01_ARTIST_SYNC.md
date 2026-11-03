# Item 1: recover the packaged artist source export

**Status:** implemented and verified; awaiting owner PR review before deployment.
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
retry behavior, backups, and durable publication are preserved.

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
  effect traces. `just ci-test` passes: **11,818 tests**, randomized seed `600338`,
  in 455.02 seconds, with the existing Starlette TestClient deprecation warning.
  Ruff, formatting, package typing, strict business/native-adapter typing, and
  independent statement/branch coverage gates pass.
- All 11 frozen CLI/API/frontend artifacts match without baseline changes.
- `just verify-wheel` passes: 689 packaged Python/frontend files match source;
  imports, 44 commands, 126 wrapped routes, and both entry points pass.
- Local preview health, password enforcement, state/source reads, and all 20
  empty active-job/reconnect routes pass. No routine was started during that smoke.

## Operator review

Preview: <http://127.0.0.1:8767/>. Unlock with `artist-sync-review`.

The server uses a private temporary copy of this branch, local state/data stores,
copied OAuth caches, and the exact deployed export pointer. Canonical review
files and publications stay in that temporary workspace. Spotify reads still use
the configured account and its existing rate limits.

1. In the Data Signal Board, run the artists Recent sync and inspect its log.
2. Verify the old export JSON error is absent. Successful completion should
   update the isolated artist source metadata.
3. Run Full if the Spotify credentials permit it. It may require many live
   requests; an existing rate-limit pause is resumable, not a completed refresh.
4. Cancel and restart a waiting refresh if desired; accepted candidates should
   resume through the existing checkpoint mechanism.

## Release and rollback

Wait for explicit PR approval. Preserve shared state/data revisions and active
job safeguards from [DEPLOY.md](../../DEPLOY.md). Deploy only the changed bootstrap
and storage modules plus the new source-recovery module. Keep operational data
and the packaged source out of the deployment overlay.

After deployment, verify code identity, health/authentication, inactive-job
endpoints, and unchanged shared artifacts before beginning recovery. Verify an
artists Recent refresh and a Full refresh, recording any genuine Spotify throttle
or maintenance-window pause separately from completed publication. Check the
durable artists metadata and resulting validated contents before merging.

No schema migration is required. Code rollback reverts the three runtime modules.
An already accepted artist refresh is valid data and is not automatically undone
with a code rollback; use its normal reviewed resource backup if data restoration
is necessary. The source-download cache is disposable.
