# Round 2, item 2: download stored Last.fm history

**Status:** implemented and verified; awaiting owner review.
**Branch:** `codex/round2-item2-scrobble-history-download`.
**Roadmap:** [second-round item 2](../IMPROVEMENTS_ROADMAP_2.md#item-2-download-stored-lastfm-scrobble-history).

## Behavior

The Last.fm row in the Data Signal Board has Download beside Sync. It saves
`lastfmstats-man-et-arms.json` from the latest complete durable publication,
preserving the original UTF-8 bytes, whitespace and filename. It does not start
or wait for a sync, hydrate the working file, or modify published data or state.
The button remains available during Recent and Full synchronization.

A download begun during a sync receives the last complete publication. Once the
replacement has been published, subsequent downloads receive that complete
version. An unpublished or partially edited working file is never a fallback.
If no stored history exists, the operator is asked to sync first.

The authenticated `GET /scrobble-history/download` route returns an attachment
with JSON content type, original content length, SHA-256 ETag and `no-store`.
It uses the deployment's existing password gate. The local pure API retains its
existing authentication boundary; `web.py` wraps it for deployment.

| Status | Meaning |
| --- | --- |
| 401 | Deployment authentication is missing or invalid. |
| 404 | No canonical history has been published; sync first. |
| 409 | Repeated concurrent publications prevented snapshot preparation; retry. |
| 502 | Manifest or stored bytes failed validation. |
| 503 | Storage configuration or temporary-file access failed; retry. |

Errors are JSON responses rather than attachments. The frontend restores the
button after success or failure and displays the server's error. Shared-state
Export uses the same existing authenticated attachment helper.

## Implementation and ownership

The route calls the named HTTP handler, which invokes
`prepare_scrobble_history_download` with a bootstrap-created `ScrobbleHistoryFiles`
resource. The application owns the missing-artifact decision; the infrastructure
resource owns a unique temporary directory for each request.

`LibraryDataService.export_snapshot` reads the validated manifest, restores the
artifact through the existing store at that revision, then checks uncompressed
size and SHA-256 using streamed file hashing. It neither parses the JSON payload
nor loads the entire history into Python memory. The Hub adapter reads an
immutable revision. The local adapter rejects a changed manifest; the service
retries up to three times with fresh metadata. Persistent conflicts fail clearly.

The synchronous FastAPI route prepares the snapshot in its worker thread.
`ScrobbleHistoryResponse`, outside the handler module, streams that independent
file through the framework. A `finally` block releases its directory on normal
completion, send failure or cancellation. Failed preparations clean up their
directory too. Separate downloads cannot delete one another's files, and no
service lock spans response delivery.

No dependency, command, state migration or data schema is added. Existing routes
and OpenAPI components are preserved; only the new GET route and its contract
fixtures are added. The wheel route counts increase by one. The board's desktop
position remains the subject of item 3.

## Owner review

- [Account preview](http://127.0.0.1:8767/?review=round2-item2).
- [Offline demo](http://127.0.0.1:8769/?review=round2-item2).
- Unlock text: `history-download-review`.

Both environments have isolated local state, files and durable publications.
The account preview uses a read-only copy of the published history. No account
routine was started. The offline demo uses synthetic Last.fm responses; its
Recent sync waits briefly and adds one synthetic play. Preview code, credentials,
data and screenshots remain outside the repository and release.

1. In the Last.fm row, click Download. Confirm the JSON attachment's filename and
   contents. The offline initial fixture has one Björk / Jóga play and retains
   deliberate Unicode and whitespace.
2. In the offline demo only, click Sync with Recent selected. Download stays
   enabled during the brief sync. A download during that wait contains the old
   complete history; one after completion includes the new synthetic play.
3. Try the controls at a narrow mobile width. Sync and Download remain usable
   without horizontal scrolling. Shared-state Export should still work.

The offline fixture has been restored after verification; its synthetic sync
results are archived privately. Both servers are healthy, serve all 734 exact
branch runtime files and have 20 idle job endpoints.

## Verification and release

The focused application, storage, authenticated HTTP, response cleanup,
bootstrap and structure checks pass (39 tests). Broader storage, architecture,
interface and web checks pass (168 tests). Checks cover missing history,
working-file isolation, real publication races, bounded retries, size/checksum
failures, concurrent snapshot ownership and cleanup after cancellation.

`just ci-test` passes **12,465 tests**, random-order seed **353221**, in
**474.13 seconds**, with **95.40%** aggregate coverage. Independent package,
domain and application statement/branch floors pass. Ruff (732 runtime files),
package typing (734 files), strict typing (487 files), dependency, structure and
lifecycle gates pass.

All **11 public artifacts** verify. Every previous OpenAPI path and component is
unchanged; the new download route is the sole addition. Wheel verification
passes for **734** exact runtime files, **44** commands, **136** wrapped routes
and both entry points.

Browser checks cover real attachments, Download remaining enabled during an
offline sync, shared-state Export and 320/390/1280 px layouts without overflow
or console errors. The browser-saved original file matches the published bytes,
including Unicode and whitespace. The concurrent sync check returns the exact
previous publication during the job and the verified new publication afterward.
The account preview's 38,789,216-byte attachment matches its stored history;
both previews leave local state and publication unchanged on download. Temporary
viewport overrides were reset.

Deployment and merge await owner approval. After approval, deploy only this
item's runtime changes, verify the authenticated download and unchanged shared
data/state, then merge and clean up. Rollback restores the prior runtime files
and removes the five new modules without altering canonical data or state.
