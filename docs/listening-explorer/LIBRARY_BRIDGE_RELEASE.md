# Listening Explorer: Library Bridge release verification

Date: 21 November 2026. Branch: `codex/listening-library-bridge`.

The owner selected current-library comparisons for the next item after the
approved Time Capsule release. The preceding release's post-merge CI passed.
The owner approved PR #92 on 21 November 2026. The Library Bridge runtime
was deployed and verified before merge.

Deployed: **https://cyborg-nomade-spotify-manager.hf.space/lastfm?tab=library&preset=all**
(private Space; existing application password applies).

Local review: **http://127.0.0.1:8765/lastfm?tab=library&preset=all**.
Local password: **`preview`**. The launcher prints the URL and password on every
start. Review runs the built wheel from an isolated temporary installation so
normal startup hydration preserves source-checkout mirrors.

## Delivered behavior

- Compare selected historical plays with published saved albums, liked tracks,
  or followed artists. Collection dates remain independent of listening dates.
- Keep one exact name candidate, unmatched names, multiple candidates and
  unavailable collections distinct. Names preserve accents, punctuation and
  edition labels. Candidate count is distinct by Spotify identity.
- Show publication dates, age, provenance and availability. No exact match is
  unresolved evidence, not proof of absence. An empty verified collection is
  known; a missing or invalid artifact is unknown.
- Show coverage by historical entities and selected plays before evidence/search
  filters. Missing album observations remain explicit in the existing overview.
- Filter collection, evidence, minimum plays and name search. Restore these
  choices from the URL. Paginate results, open original history, and inspect
  up to five Spotify candidates with their complete distinct count.
- Export the current page as CSV with both source identities, publication dates,
  options and explicit page scope. Export the coverage chart as PNG.
- Keep historical totals usable when collection reads fail, with an independent
  recovery control. Existing views remain independent of collection readiness.

## Architecture and contracts

[ADR 004](../adr/004-published-library-evidence.md) records the matching and source
decisions. Three collection artifacts come from one immutable manifest revision;
each successful artifact is independently size/checksum verified. A manifest
conflict cannot publish a mixed generation. Complete decoded artifacts are
cached by checksum; source failures do not erase available historical counts.

Collection refresh uses one bounded owned worker, keeps two complete generations
and drains cancelled shutdown before discarding derived data. Existing routine
jobs still close before analytics workers. The new pure application use case
calls the domain comparison directly with explicit resources.

Two additive protected GET routes are included:

- `/lastfm/analytics/library/status`: independent readiness and publication token.
- `/lastfm/analytics/library`: bounded comparisons with history and collection
  version tokens, existing listening filters and collection-specific options.

Analytical responses remain `private, no-store`. Existing route and OpenAPI
schemas were compared to master and preserved. Only the additive API contracts
were recorded; source/dependency inventories stay frozen. One data-free helper
receives an exact static allowlist entry. All mutable module/style URLs now use
revision `v=3`, retaining the prior warm-cache protection.

## Verification

Hand-calculated domain tests cover category/count reconciliation, Unicode and
artist context, punctuation/edition preservation, duplicate identities,
ambiguous candidate bounds, unavailable collections, thresholds, filtering,
ordering and pagination. The new domain, application, acquisition and runtime
modules reach **100% statement and branch coverage** in the focused suite.

Storage/lifecycle tests cover one pinned revision, unchanged managed files and
durable revision, checksum failure, invalid rows/JSON, cache reuse, generation
expiry, stale recovery, one-worker ownership and cancellation-drained cleanup.
Actual gated HTTP tests verify both version tokens, private cache policy,
selected-date counts, unknown follows, input bounds and authentication.

Thirteen Chrome scenarios cover the existing explorer plus real rendering,
chart height, comparisons, ambiguity, source dates, URL restoration, exports,
original-record navigation, safe external names, mobile width, source failure
and recovery. Visual inspection caught and corrected a zero-height chart
container; its rendered dimensions are now asserted in the browser suite.

Ruff, package/strict business typing, structure and callback checks pass. All
11 frozen-interface checks pass. Wheel smoke checks **777 packaged Python/frontend
files** against source and retains the 45 existing commands and both entry points.
The approved runtime passes all three [hosted quality checks](https://github.com/cyborg-nomade/spotify-manager/actions/runs/44771094682):
**12,713 randomized tests**, independent statement/branch coverage floors,
thirteen browser scenarios, seven JavaScript checks, typing, architecture
and packaging. The PR records checks for the final release-documentation commit.

## Published-source check

The read-only benchmark acquired **339,298 published scrobbles** and all three
collection artifacts from manifest revision
`5f124adc63c00fe5bd025a4d2e127480ce38c26a`.

| Collection | Distinct Spotify identities | Historical entities | One name candidate | Unmatched | Multiple candidates |
| --- | ---: | ---: | ---: | ---: | ---: |
| Followed artists | 37,924 | 15,696 | 11,225 | 4,268 | 203 |
| Saved albums | 4,217 | 31,502 | 3,899 | 27,596 | 7 |
| Liked tracks | 44,986 | 121,906 | 39,838 | 81,099 | 969 |

Collection acquisition and verification took 5.69 seconds locally. Complete
history comparison, including indexed reads, took 0.62 seconds for artists,
0.31 seconds for albums and 0.63 seconds for tracks. These are local cold-query
measurements, not Space latency guarantees or verified membership statistics.
Exact repeated queries use bounded application result caching.

History token:
`v1-1e86aeeb6a8c5e232d0825672949a9628f90b21824fb3689b47a7a49cd436c5b`.
Collection token:
`l1-cc3645a7a477cfa02f27312279234f38b93c8a5b3615cab08d431ed604066f1b`.
Source dates and checksums are retained in the local ignored benchmark report.

## Release boundary

The owner approved this release after local review. No canonical-data or
shared-state migration was needed. Rollback restores code and discards derived
caches; durable datasets remain independent of the Space code.


## Approved deployment

Approved runtime: `dabad6bbd31071e9b2d0fea5a9816e6ad96e25b3`.
Space revision `cdd3c0cf9d63c8a70fe68bce3304a62157d54b4c` replaces
`375836dd33bfcd6227010de29ed4fde568262fe8`. Exactly **14 runtime files** were
uploaded with an optimistic parent guard; every deployed byte was read back
against the approved Git source. Previous bytes were retained locally for code
rollback. Both datasets retained their predeployment revisions:

- State: `a2ee4809e9414b993c95583f75a4a50d8f461e39`.
- Library data: `16c52efa18ae5c790b19b5a7871f6c29ae5cf322`.

The [read-only preflight](https://github.com/cyborg-nomade/spotify-manager/actions/runs/44889205495)
confirmed healthy access, all four durable artifacts and no active jobs across
20 routine endpoints. The [authenticated postdeployment verifier](https://github.com/cyborg-nomade/spotify-manager/actions/runs/44889586926)
then passed existing explorer checks and all new collection checks:

- All analytical totals agree across **339,344 published scrobbles**.
- Musical Eras retains all 229 periods; raw weighted-share and anniversary
  checks, yearly fallback, entity details and original records pass.
- All three collection coverage totals reconcile to the selected history,
  excluding the explicitly reported missing-album plays for saved albums.
- Candidate names, distinct IDs, bounded evidence, ambiguity filters, applied
  options and independently pinned source tokens agree.
- Both new data routes reject missing application credentials.
- Source-download checksum and unchanged shared state after reads pass.
- Eight live HTTP shell/module/style routes match approved bytes and cache
  policies, including the new helper and pinned vendor library.

An initial temporary verifier incorrectly treated artist display context as a
second artist-identity component. A dimension-specific identity probe isolated
that verifier error. The corrected verifier checks artist names alone and
artist/title pairs for albums and tracks; production code was unchanged.

Verified history token:
`v1-ebabfbb0f0d26e62da8d7bc091fcc5bb52d9db697eeb6177ebf0d7a6ef5ca324`.
Verified collection token:
`l1-0592adc4603551ae3398f3973e0511738307baaf956f9aa88a0eca4846194015`.
The Space remains private. Verification uses existing read-only Actions
credentials on an isolated temporary branch, without refreshes, synchronization,
playlist changes or state publication. The temporary branch/worktree is removed
after release.
