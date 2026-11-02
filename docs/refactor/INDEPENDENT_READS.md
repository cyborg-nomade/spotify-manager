# Item 10: proven independent reads

**Status:** approved, deployed, verified and merged in PR #70 on 2026-10-30.
Reviewed source `00143c2` was based on Item 9 merge `016c62a`; Item 10 merge is
`3cb2f78`.

## Measured change

The native artist-statistics catalog now reads at most four independent album
batches concurrently. It retains the existing 20-ID endpoint batches, raw ID order,
duplicates, parsing, first-credit rules and final track ordering. Identical batches
share their pending request and successful metadata within this single catalog
operation. A bounded cache retains at most 32 batch entries and is cleared on
every exit, including errors and cancellation.

The original serial implementation remains the compatibility path for
caller-owned SDK clients and the differential oracle for the native optimization.
The existing frozen behavior fixtures, wire snapshots and frontend source are
unchanged. No new configuration, endpoint, retry policy or credential rotation is
introduced.

The baseline is recorded against `016c62a` in
[`baseline.json`](../../tests/read_efficiency/fixtures/baseline.json). These are
synthetic complete-catalog inputs, not measurements of a live Spotify account:

| Catalog input | Original requests / peak overlap | Native requests / peak overlap | Ordered result IDs |
| --- | --- | --- | --- |
| 80 distinct album IDs | 4 / 1 | 4 / 4 | Same 80 IDs |
| The same 80-ID catalog twice | 8 / 1 | 4 / 4 | Same 80 IDs |
| 80 identical album IDs | 4 / 1 | 1 / 1 | Same single ID |

The last case still sends the original 20 duplicate IDs in its one upstream
request. It shares identical operations rather than silently rewriting an
endpoint's batch or a caller's returned sequence.

An illustrative offline run with a simulated 25 ms delay per read measured about
0.107 s versus 0.026 s for the distinct catalog, and 0.214 s versus 0.027 s for the
repeated catalog. Request counts, overlap and identical ordered results are the
correctness gates; elapsed time is not. These figures do not claim a measured
live-service speedup.

## Follow the implementation

The existing route remains beside `api.artist_stats`. Follow its named HTTP
handler into `application.library_lookup_run.artist_statistics`:

```text
resolve artist
  → discover release IDs using the original dependent offset pages
  → read fresh saved-release membership in the original batch order
  → SpotifyArtistLookup.tracks
      → processors.library_lookups._live_primary_track_ids
      → native client: AlbumCatalogReads.primary_tracks
          → admit at most four existing album batches
          → await all admitted responses
          → decode responses in input order
          → lookup_catalog.collect_album_tracks
              → fixed primary-credit rule
              → each album's dependent track pages, sequentially
      → SDK compatibility client: original lookup_catalog.primary_tracks
  → read fresh liked-track membership in the original batch order
  ← original ArtistLibraryStats response
```

[`AlbumCatalogReads`](../../spotify_manager/infrastructure/catalog_reads.py) is a
small concrete resource owner, constructed for that catalog operation. It calls
the named page reader directly. The existing parser/collector is shared with the
serial path; business rules and application orchestration are not duplicated.
There is no callback dispatcher, global metadata cache or hidden application stage.

A typed `AlbumResponse` distinguishes malformed returned data from an exception
raised by an operation. This preserves the old parser error even if a broken
resource override returns an exception object as data. Original raised errors,
including process-control exceptions, reach the caller with their identity intact.

## Independence and freshness boundaries

| Read or effect | Scheduling decision and reason |
| --- | --- |
| Complete album batches for known IDs | Overlap a four-request window: IDs are already discovered, all batches are required, and no decision or mutation occurs inside the metadata operation. |
| Dependent artist/track pages | Preserve sequential pagination, raw offset/cursor authority, distinct malformed-page errors and primary-credit filtering. |
| Saved/liked membership | Preserve fresh sequential observations. They run outside the metadata cache, in their original before/after positions. |
| Discovery and New Wine observations | Retain the existing invocation caches and their thresholds, live-membership rules and original read order. Do not prefetch releases that a qualification or history prefilter would skip. |
| History/recommendation reads | Retain existing canonical-history loading, run caches, ordered seed selection and exclusion updates. Their current dependencies do not justify speculative reads across decisions. |
| Playlist writes, accepted checkpoints and publication | Remain ordered and sequential. The catalog operation has already drained and discarded its cache before control returns to these stages. |
| Authentication and connection ownership | Reuse Item 9's native pool and coordinated per-credential refresh. A four-read window and 32-entry cache are resource bounds, not assumed Spotify quotas. |

The new reader does not add a retry. HTTP statuses, Retry-After, ambiguous mutation
handling and each caller's existing adapter/outer retry profile retain their
owners. Already-admitted independent metadata requests may finish after another
batch fails. They are drained before the original first error is exposed in
catalog traversal order. A malformed earlier album or its failing dependent page
still takes precedence over an error from a later batch. Transport diagnostics
retain the existing per-invocation output owner.

Cache keys preserve the complete ordered ID batch. The reader uses one supplied
client/profile and is never shared across independent requests or jobs. Its
explicit exit invalidation prevents reuse across an operator choice, subsequent
lookup, library mutation, account change or later invocation. Failed reads do not
poison subsequent calls, and old completed entries are evicted when the resource
bound is reached.

## Reproduce the evidence

```console
just test-read-efficiency
just benchmark-reads --count 80 --repeat 1 --latency 0.025
just benchmark-reads --count 80 --repeat 2 --latency 0.025
.venv/bin/pytest tests --random-order --random-order-seed=20261029 -q --cov=spotify_manager --cov-branch --cov-report=json:/tmp/item10-coverage.json
.venv/bin/python docs/refactor/capture_baseline.py --write --output /tmp/item10-interfaces
.venv/bin/python docs/refactor/check_interfaces.py /tmp/item10-interfaces
```

The focused gate covers the real native HTTP/credential/pool path and the actual
ASGI artist-statistics endpoint, including its public success/error responses.
Controlled barriers prove out-of-order completion, bounded overlap, cancellation,
sibling draining and exact first-error precedence. It also compares the retained
SDK path, duplicate batches, empty inputs, missing rows, malformed response
values, pagination and bounded-cache eviction. No elapsed-time threshold, live
credential, production data or Spotify write is part of these tests.

Final verification on 2026-10-29:

- **11,049 tests passed**, randomized seed `20261029`, in 390.35 seconds.
  The existing Starlette TestClient dependency warning is the only warning.
- Package coverage: **95.69% statements** (36,478 / 38,120), **92.17% branches**
  (5,794 / 6,286), **95.19% combined**. No coverage exclusions were added.
- Domain and application retain **100% statement and branch coverage**.
- `just test-read-efficiency` passes **73 tests** and a **100% statement/branch**
  gate for the new resource, plus strict typing for its production and test files.
- Ruff/formatting pass across **1,107 files**. Package and nightly-script typing
  pass **686 files**; strict inner-layer/native checks pass **410 files**.
  Changed functions pass the flatness, annotation, parameter and size audit.
- All **11 frozen public artifacts** match; original behavior fixtures, interface
  baselines and frontend source are unchanged. Relative documentation links resolve.
- Source distribution and wheel both build successfully; the new catalog module
  is included in the built wheel.
- Read-only local smoke checks pass for health, password enforcement, shared state,
  source status and all **20 reconnect endpoints**, with no active jobs. The latest
  four local operator files remain byte-identical after startup and verification.

## Local review

The item was reviewed at **http://127.0.0.1:8766/** with nonempty local unlock
text. The artist-statistics instrument exercises the new native
catalog reader. Existing workflow and dry-run behavior is preserved. The latest
four operator files are retained separately, restored after startup hydration and
excluded from the implementation commit.

## Approved release

The release waited for an active New Kids job to finish. Read-only access checks
[before](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41054842125)
and [after](https://github.com/cyborg-nomade/spotify-manager/actions/runs/41055113461)
deployment passed authentication, shared state, all four durable artifacts and all
20 reconnect endpoints with no active jobs.

The code-only Space commit `1af40380320cc06f198e13b2a33574fa393bc1f1` contains exactly
the three reviewed Python changes. Each deployed blob was verified against Git,
and the Space reached RUNNING before PR merge. Rollback code revision:
`ed9b701feb20843361cfb70a6ea566e050630549`.

The independent state (`5dcf65d4e7e7c46a292377d3a0f56d463e7e56dd`) and data
(`f862ffc03bacc16e5bee8b5d7c948c3f2cefac7e`) datasets were unchanged by deployment.
The latest four operator files and all previous stashes were preserved during
cleanup. The merged Item 10 branch was removed and clean, updated master was
verified before Item 11 started.

[Item 11](TYPING_AND_ARCHITECTURE.md) completes strict typing and architecture
enforcement; Item 12 runs
the final compatibility and documentation audit. Frontend source restructuring
remains a separate future refactor.
