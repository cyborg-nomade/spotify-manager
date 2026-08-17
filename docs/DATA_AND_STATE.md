# Data and State

## Why this directory matters

`spotify_manager/files/` is both the application's data directory and its
lightweight persistence layer. It contains very different kinds of files:

- externally produced source exports;
- generated mirrors of Spotify and Last.fm;
- restart-safe routine state;
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
4. Routine state files are authoritative for application-owned cursors,
   mappings, processed ids, pending choices, and resumable batches.
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

### Routine state

State files are small JSON documents written atomically through a sibling
temporary file. Depending on the routine they may contain a cursor, active run,
starting playlist snapshot, completed item ids, release ordering, artist
mappings, permanent skips, annual imports, or a pending interactive decision.

| State file | Important contents |
| --- | --- |
| `genre_reveal_state.json` | Completed genre slugs and display preference. |
| `review_album_limits_decisions.json` | Persisted keep decisions across album-review runs. |
| `new_wine_flush_state.json` | Starting batch, completed transitions, liked-tail progress, and Wine Cellar refill state. |
| `new_kids_state.json` | New Kids and Queue 2 active runs, completed releases, and yearly playlist data. |
| `queue_state.json` | The Queue recommendation/flush state and processed artists. |
| `queue_3_state.json` | Queue 3 active run, composer playlist mappings, annual import, and release progress. |
| `slow_listening_flush_state.json` | Current two-item batch, skipped track candidates, and release ordering. |
| `release_check_state.json` | Last successful check date, artist mappings, permanent artist/release skips, processed release ids, pending singles, and active run. |
| `palace_of_memory_state.json` | Persisted alphabetical cursor. |
| `discography_routine_state.json` | Next source queue in the round-robin plan. |

Some state files are intentionally absent until the first run. Their
conventional paths are declared as `DEFAULT_STATE_PATH` in the corresponding
routine module.

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
| `genre_reveal_state_backups/` | Snapshots before Genre Reveal state replacement. |
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

The repository working tree is the runtime filesystem. State, logs, caches, and
backups persist until they are moved or deleted. Most runtime files are ignored
by Git to prevent accidental commits and merge conflicts.

### Hugging Face execution

The Space repository supplies the files present at container startup. The
running container then modifies its own writable copy. Unless the Space has a
mounted persistent volume or the file is exported before a rebuild, those live
writes are not automatically committed back to the Space repository.

This creates three potentially different versions:

1. local workstation state;
2. state stored in the Space repository revision; and
3. newer state in the running Space container.

The running container is authoritative after a live routine has changed its
state. Before deployment, snapshot it and never replace it with an older local
copy. See [DEPLOY.md](../DEPLOY.md#state-preserving-update) for the required
preflight and verification process.

For robust long-term operation, mount persistent Hugging Face storage and point
runtime paths there where the application exposes a path override. Until all
routine paths are configurable, state snapshots remain part of every release.

## Recovery playbook

### Interrupted routine

1. Do not delete its state file or cache.
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

### Invalid or corrupt state JSON

1. Stop the routine and make a byte-for-byte copy of the file and adjacent
   `.tmp` file.
2. Inspect the routine's backup directory and audit log.
3. Prefer restoring a known snapshot over hand-editing.
4. If manual repair is necessary, preserve ids and completed-item lists and
   validate the result with the routine's `load_state` function or tests before
   a live run.

### Deployment state mismatch

Do not immediately redeploy. Keep the pre-deployment backup and the old Space
revision. Compare path lists, sizes, blob ids, and LFS hashes. Roll the Space
repository back to the previous revision if code or state changed outside the
approved deployment set.

## Privacy and version control

- Keep the GitHub repository and Hugging Face Space private if they contain the
  real exports.
- Never commit `.env` or `spotify_manager/auth/spotipy_token_cache*.json`.
- Review `git status --short --ignored spotify_manager/files` before assuming an
  ignored state file is current or expendable.
- Avoid broad cleanup commands against `spotify_manager/files/`.
- Commit generated source exports or mirrors only when intentionally recording
  a known snapshot. Keep secrets out of commit messages and logs.
