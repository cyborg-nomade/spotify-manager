# Data and State

## Why this directory matters

`spotify_manager/files/` is the application's data directory. Durable routine
state is stored separately in one shared, versioned `state.json` document. The
files directory still contains several other kinds of data:

- externally produced source exports;
- generated mirrors of Spotify and Last.fm;
- legacy routine-state sources retained for migration and audit;
- caches that reduce API cost;
- append-only audit logs; and
- backups and analysis staging data.

These categories have different ownership and recovery rules. A file being
listed in `.gitignore` does not mean it is disposable. Many ignored files hold
the only current cursor, artist mapping, pending decision, or audit trail for a
deployed routine.

## Source-of-truth hierarchy

1. Live Spotify is authoritative for current playlists, saved albums, liked
   tracks, and followed artists.
2. Last.fm plus the canonical local scrobble export is authoritative for
   listening history.
3. Canonical Spotify mirrors are snapshots used when a routine needs a complete
   inventory or when repeated live lookups would be too expensive.
4. The private Hugging Face state dataset is authoritative for
   application-owned cursors, mappings, processed ids, pending choices, and
   resumable batches.
5. Audit logs record what was planned or changed and support review and manual
   recovery; they are not normally replayed automatically.
6. `YourLibrary.json` is an offline source export. It is used deliberately by
   export-only and legacy commands, not as a silent substitute for a focused
   live lookup.

## File families

### External source exports

| Path | Owner | Use |
| --- | --- | --- |
| `files/YourLibrary.json` | Spotify export process | Offline library source for `analyse-library-async`, counts, restoration, and legacy workflows. |
| `files/lastfmstats-man-et-arms.json` | Last.fm export plus `update-scrobble-history` | Canonical scrobble history shared by every Last.fm routine. |
| `files/lastfmstats-man-et-arms.json.gz.b64.part-*` | `upload-library-files-to-hf` | Deterministic compressed fallback representation of the large Last.fm export. |

Fresh source files can be validated and uploaded with
`upload-library-files-to-hf`. The scrobble updater creates a timestamped gzip
backup before replacing the canonical Last.fm file.

### Canonical live mirrors

| Path | Contents |
| --- | --- |
| `files/albums_total_new.json` | Saved Spotify albums in Spotify-style alphabetical order. |
| `files/liked_tracks_total.json` | Liked Spotify tracks. |
| `files/artists_total.json` | Followed Spotify artists. |
| `files/stats_history.json` | Dated counts and growth history derived from the mirror set. |

The web **Data signal board** refreshes albums, tracks, and artists independently.
Albums and tracks default to an incremental recent refresh: new items are merged
without removing older mirror entries. Artists still require a cursor walk, but
recent mode avoids extra reconciliation passes. Use full mode occasionally to
remove items that have been unsaved, unliked, or unfollowed.

Some routines perform their own focused live verification. For example,
no-discovery New Wine uses mirror ids as candidates but checks liked tracks and
saved albums through Spotify before qualifying an artist. Palace of Memory
performs a complete saved-album refresh before selecting its alphabetical half.

### Separate analysis products

The explicit analysis commands do not overwrite the canonical mirror names:

| Mode | Source | Outputs |
| --- | --- | --- |
| `async` | `YourLibrary.json` only | `albums_total_new_async.json`, `liked_tracks_total_async.json`, `artists_total_async.json`, `stats_history_async.json` |
| `sync` | Live Spotify API only | `albums_total_new_sync.json`, `liked_tracks_total_sync.json`, `artists_total_sync.json`, `stats_history_sync.json` |
| `mirrors` | Live API, resource-specific or all | Canonical filenames listed above |

Each mode has a workspace such as `files/library_analysis_sync/`, a JSON-lines
event log, and a backups directory. Live analysis stages pages before publishing
a complete JSON file. It reconciles changes made while a scan is running and
can resume from its checkpoint.

Use the printed run id to undo a completed analysis publication:

```console
just restore-library-sync RUN_ID --yes
```

### Shared routine state

All production state access goes through `StateService`. Its default adapter
stores one `state.json` file in the private Hugging Face dataset
`cyborg-nomade/spotify-manager-state`. The document has a schema version,
document timestamps, and independently timestamped namespace envelopes. A
namespace write reloads the latest document, merges only that namespace, and
uses the dataset commit as an optimistic concurrency guard.

| Namespace | Important contents |
| --- | --- |
| `genre_reveal` | Completed genre slugs and display preference. |
| `review_album_limits` | Persisted keep decisions across album-review runs. |
| `review_artists` | Completed artists and pending unfollow/queue-move plans. |
| `recover_removed_albums` | Processed albums and checked credited artists. |
| `new_wine` | Starting batch, completed transitions, liked-tail progress, and Wine Cellar refill state. |
| `new_kids` | New Kids and Queue 2 active runs, streaks, and yearly playlist ids. Played-release progress comes from the current year's Last.fm history. |
| `queue` | The Queue artist mappings and resumable flush. |
| `queue_3` | Active run, composer routes, annual import, and release ordering. |
| `slow_listening` | Current two-item batch, skipped candidates, and release ordering. |
| `release_check` | Last check date, mappings, permanent skips, processed releases, pending singles, and active run. |
| `palace_of_memory` | Persisted alphabetical cursor and last album identity. |
| `discography` | Next source queue in the round-robin plan. |

The former per-routine JSON files and log-derived progress are legacy migration
inputs. Explicit non-default paths remain supported for tests and recovery, but
normal CLI and web execution never treats them as production state.

Use the same controls from local CLI or the authenticated web cockpit:

```console
just state-show
just state-show --namespace release_check
just state-export spotify-manager-state.json
just state-edit spotify-manager-state.json
```

`state-edit` validates the whole document, rejects stale exports unless
`--force` is explicit, asks for confirmation, and uses the current store
revision as a final write guard. The Data Signal Board provides the same view,
edit, and export operations. Guided mode renders finite choices as dropdowns,
booleans as checkboxes, numbers as numeric inputs, and large objects as lazy
collapsible branches. Generated fields are read-only there; Advanced JSON is
the explicit escape hatch. Hugging Face commit history is the backup chain.

### Audit logs

Audit logs are append-only JSON Lines (`.jsonl`), usually one event or completed
decision per line. Common examples include:

| Log family | Records |
| --- | --- |
| `library_analysis_*_log.jsonl` | Run ids, pages, retries, backups, publication, cancellation, and restore events. |
| `scrobble_history_update_log.jsonl` | Last.fm fetch range, merge counts, backup, and replacement. |
| `removed_albums_log.jsonl` / `removed_albums_recovery_log.jsonl` | Album removals, credited-artist follow checks, and restored future releases. |
| `found_art_log.jsonl`, `sauvignon_recommendation_log.jsonl`, `queue_log.jsonl` | Recommendation seeds, rankings, selected items, and additions. |
| `new_wine_flush_log.jsonl`, `new_kids_log.jsonl`, `queue_2_log.jsonl`, `queue_3_log.jsonl` | Playlist transitions and release decisions. |
| `slow_listening_flush_log.jsonl`, `requeue_for_a_dream_log.jsonl` | Discography advances and completion. |
| `release_check_log.jsonl` | Release eligibility, approvals, destinations, skips, and additions. |
| `palace_of_memory_log.jsonl`, `palace_of_memory_album_refresh_log.jsonl` | Random/alphabetical selections, cursor changes, and album mirror refreshes. |
| `discography_routine_log.jsonl` | Selected release sets and marker removals. |

Logs can contain Spotify ids, artist/title metadata, and personal listening
history. Treat them with the same privacy as the source exports.

### Caches

Caches reduce repeated Spotify or Last.fm requests and are safe to rebuild when
the associated command supports it:

| Cache | Purpose |
| --- | --- |
| `album_tracks_cache.json` | Album track lists used by repeated evaluations. |
| `artist_review_cache.json` | Catalog candidates for resumable artist review. |
| `found_art_cache.json` | Friday-window Last.fm similar-track responses shared by recommendation routines. |
| `queue_recommendation_cache.json` | Similar-artist recommendation responses. |
| `found_art_recent_scrobbles.jsonl` | Legacy append-only Last.fm delta absorbed by the canonical updater. |

Do not delete a cache during an active run. A cache can also carry the exact
candidate set needed for deterministic resumption, even if it is technically
derivable.

### Backups and staging

| Directory | Purpose |
| --- | --- |
| `lastfm_history_backups/` | Gzip snapshots before canonical scrobble replacement. |
| `palace_of_memory_album_backups/` | Saved-album mirrors replaced by Palace preflight refresh. |
| `library_analysis_*_backups/` | Undo snapshots for published analysis/mirror files. |
| `library_analysis_*/staging/` | Page-level temporary data for resumable analysis. |

Temporary `.tmp` files are adjacent atomic-write artifacts. If one remains after
a crash, the non-`.tmp` file is still the last published version.

### Legacy files

`albums_total.json`, `comparison.json`, `control_file.json`, `stats_file.json`,
`liked_tracks.json`, and related root-level safety copies belong to the original
monthly reconciliation workflow. They remain supported by the legacy commands
documented in the README. New routines should not adopt them unless they are
participating in that workflow.

## Dry-run persistence rules

Dry run means no Spotify playlist or library mutation. It does not universally
mean no local write:

- `check-new-releases --dry-run` can refresh and back up the canonical scrobble
  history, save confirmed Last.fm-to-Spotify artist mappings, and save permanent
  artist skips. It does not persist release decisions or additions.
- Palace of Memory refreshes the saved-album mirror before both dry and live
  selection so its cursor refers to current data.
- recommendation routines can update resumability caches and write a dry-run
  audit record.
- cursor-only commands deliberately persist the requested cursor even though
  they do not mutate Spotify.

Read the command's README section before assuming a dry run is filesystem
read-only.

## Local and deployed persistence

### Local execution

The CLI and local web app use the same Hub-backed state service as production,
so their durable routine state is immediately shared with the HF web app. Logs,
caches, mirrors, and backups still live in the local working tree.

### Hugging Face execution

The Space reads and writes the same private dataset. Container rebuilds do not
roll back routine state, and code deployment must not upload a replacement
`state.json` into the Space repository. `SPOTIFY_MANAGER_STATE_TOKEN` must have
read/write access to the private dataset.

The old New Release Check browser mirror remains as a compatibility recovery
layer. Any accepted restore now writes through `StateService`, and the replaced
state remains available in Hub commit history.

Container-local logs, caches, mirrors, backups, and analysis staging are still
ephemeral unless copied to the Space repository or another persistent store.
Deployment snapshots remain important for those data families, but no longer
for routine state.

## Recovery playbook

### Interrupted routine

1. Inspect the namespace with `state-show`; do not clear it or its cache.
2. Check the corresponding JSON-lines log for the last successful mutation.
3. Re-run the same command and mode. Resumable routines detect their active run.
4. If the playlist was edited manually, start with a dry run and compare the
   planned action with live Spotify before continuing.

### Stale canonical mirror

Run the resource's incremental refresh for fast additions. Use full mode when
you need removals reflected as well. If a full scan is repeatedly interrupted,
keep its checkpoint and resume rather than deleting its staging directory.

### Bad analysis publication

Use `restore-library-sync RUN_ID --yes` with the run id from the summary or
event log. This restores the files from the analysis backup manifest.

### Invalid or corrupt shared state

1. Stop active routines and export the current state if it is readable.
2. Inspect the private dataset commit history and the corresponding audit log.
3. Restore a known Hub revision or repair an exported snapshot.
4. Apply a repair with `state-edit`; validation and revision guards run before
   the shared document is replaced.

### Deployment state mismatch

Do not immediately redeploy. Compare the state dataset revision shown by local
and web `state-show` controls. The same revision should be visible from both.
Use Hub history to inspect or restore a bad state write; roll back the Space
repository only when the mismatch is in code or container-local data.

## Privacy and version control

- Keep the GitHub repository and Hugging Face Space private if they contain the
  real exports.
- Never commit `.env` or `spotify_manager/auth/spotipy_token_cache*.json`.
- Review `git status --short --ignored spotify_manager/files` before assuming an
  ignored state file is current or expendable.
- Avoid broad cleanup commands against `spotify_manager/files/`.
- Commit generated source exports or mirrors only when intentionally recording
  a known snapshot. Keep secrets out of commit messages and logs.
