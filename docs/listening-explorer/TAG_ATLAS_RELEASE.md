# Listening Explorer: Tag Atlas release verification

Date: 21 November 2026. Branch: `codex/listening-tag-atlas`.
Status: owner approved PR #93 on 21 November 2026; runtime deployed and verified.

Deployed: **https://cyborg-nomade-spotify-manager.hf.space/lastfm?tab=tags&preset=all**
(private Space; existing application password applies).

The preceding Library Bridge release is deployed and PR #92 is merged. This
release follows with current community-tag enrichment, as described in
[ADR 005](../adr/005-current-community-tag-evidence.md).

Local review: **http://127.0.0.1:8765/lastfm?tab=tags&preset=all**.
Local password: **`preview`**. Startup prints both values. The review runs the
candidate wheel from an isolated installation; hydration and derived caches
remain outside checkout mirrors.

## Delivered behavior

- Tags & genres plots monthly allocations using current Last.fm community tags.
  Choose the leading tag or equal allocation among up to three leading tags,
  and allocated plays or share. Eight leading tags, Other, and Unknown reconcile
  with every selected recorded play.
- Coverage reports actual plays and artists, with never-looked-up, empty, and
  unresolved observations distinct. Retrieval dates describe current metadata,
  never historical genre knowledge. Source credit and artist tag links are
  visible; original provider labels remain available in artist evidence.
- Opening or filtering a chart never triggers provider requests. Fetch an
  explicit batch of 10, 25, or 50 highest-play missing/stale artists. Recent
  observations are skipped for thirty days unless force refresh is selected.
  Progress and cancellation retain completed observations.
- Evidence supports tag filtering, artist search, pagination, history detail,
  URL restoration and CSV. Monthly allocations have a table and complete CSV;
  the chart exports PNG. Exports identify both versions, source dates, allocation
  and applied evidence scope.
- Provider/cache failures and expired tag versions recover independently of
  history. An unavailable API key leaves cached views available.

## Operations and contracts

Optional existing `LASTFM_API_KEY` enables public artist tag reads. No Last.fm
user session is required. `LISTENING_TAG_CACHE_DIR` selects an app-owned directory;
the default is `spotify-listening-tags` under the system temporary directory.
The fixed `artist-tags-v1.sqlite` file is derived metadata, not canonical data.
Use a separate directory per process. Cache files survive process restart while
the directory remains; temporary-directory cleanup or Space rebuild may remove
them. Stop the process before deleting this cache to reset it. Only explicit
new lookup batches refill it. Do not put the cache in a public/static directory.

Four additive protected routes preserve all preceding operations and schemas:

| Method and route | Purpose |
| --- | --- |
| `GET /lastfm/analytics/tags/status` | Metadata version and owned batch progress. |
| `GET /lastfm/analytics/tags` | Cached allocations pinned by history and metadata tokens. |
| `POST /lastfm/analytics/tags/refresh` | Explicit bounded public reads and derived cache writes. |
| `POST /lastfm/analytics/tags/cancel` | Cancel enrichment while draining the active operation. |

All routes retain the web password gate and private, no-store responses.
Canonical files, collection publications, routine state and playlists are
unchanged. Source/dependency inventories remain frozen. Mutable explorer module
and stylesheet URLs advance together to revision 4; the chart vendor stays pinned.

## Verification

Focused tests cover allocation conservation, Other/Unknown, timezones, freshness,
source identity and malformed/error responses, secret-free failures, persistent
cache restart/eviction/corruption, independent metadata expiry, authentication,
single-batch ownership and cancellation during an atomic cache commit.
The new domain/source/cache calculations have full statement and branch coverage.
Fifteen browser scenarios and seven JavaScript checks pass, including all
existing explorer scenarios, explicit fetching, URL restoration, exports,
metadata failure recovery and mobile layout. Final CI and real-history preview
results are recorded in the review PR.

The isolated candidate wheel contains 786 verified Python/frontend files and
passes both entry-point checks and all 45 CLI command checks. Package typing,
strict business/test typing, 162 architecture/bootstrap/lifespan checks and
eleven frozen-interface comparisons pass. Fifty focused feature tests achieve
100% statement coverage and 99.82% combined statement/branch coverage across
the new calculation, application and concrete cache/provider modules.

The real published history contains 339,344 scrobbles and 15,696 artist
identities. Both allocation modes reconcile all 339,344 plays over 229 monthly
buckets with an empty metadata cache. The preview password gate and private
response headers pass. Following explicit owner approval, one live batch looked
up the twenty-five highest-play artist names. All twenty-five returned tags,
covering 94,235 selected plays (27.8%). Both allocation modes still reconcile
339,344 plays across 229 months, with the same history checksum. A fresh cache
reader restores all twenty-five observations with the identical metadata token;
the API key is absent from the cache. The populated graph, leading-tag mode and
share display were checked in the real-history preview. Synthetic provider
fixtures also exercise failure, cancellation and metadata expiry.

## Approved deployment

Approved runtime: `7db633cc2830b2f7adff6631496cce1aa9472cad`.
Space revision `47cc639db9ea2967cba8b8fdeef7edc869f9ff62` replaces
`cdd3c0cf9d63c8a70fe68bce3304a62157d54b4c`. Exactly seventeen runtime files
were uploaded with an optimistic parent guard, then read back against the
approved Git bytes. Previous bytes and newly introduced paths are recorded for
rollback. The Space remains private. Durable revisions are unchanged:

- State: `a2ee4809e9414b993c95583f75a4a50d8f461e39`.
- Library data: `16c52efa18ae5c790b19b5a7871f6c29ae5cf322`.

[Approved-head CI](https://github.com/cyborg-nomade/spotify-manager/actions/runs/44894144242)
passed 12,767 tests, every independent coverage floor, 475 architecture/dependency
checks, fifteen browser scenarios, seven JavaScript checks and the wheel smoke.
The final documentation commit changes no runtime files; its CI and the
fifteen-minute health observation are recorded in the review PR.

Read-only preflight and postdeployment verification used existing local access
credentials without logging them. Both checks reconciled all 339,344 scrobbles,
entity records, anniversary counts, 229 Musical Eras periods and all three
published collection comparisons. The history download checksum and shared-state
revision remained unchanged. Eight live HTTP shell/module/style routes match
the approved source bytes. Both tag allocation modes preserve all 339,344 plays;
all four tag routes reject missing application credentials. No production
provider batch was started. The new production cache is empty, so all plays are
explicitly Unknown until the owner requests lookups; the approved local preview
observations are independent of that cache.

Rollback is warranted if authentication permits a data-gate bypass, analytical
totals disagree, a critical view fails, or health requests repeatedly fail after
startup. Restore the preceding code bytes and remove only the newly introduced
runtime paths, using the retained manifest and optimistic revision guard.
Canonical data and shared state require no rollback or migration.
