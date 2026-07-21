---
title: Spotify Manager
emoji: 🎧
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Personal Spotify library manager web UI
---

# Spotify Manager

A small mobile-first web UI over the Spotify Manager FastAPI backend, so the
library lookups and maintenance commands are usable from a phone.

This Space runs the app defined in `spotify_manager/web.py` (the pure API lives
in `spotify_manager/api.py`). It is protected by a shared password and talks to
Spotify with a pre-seeded OAuth token.

See **DEPLOY.md** for full setup: required secrets, how to generate the token
cache, and security notes.

## Library analysis

The library mirror is built through two deliberately separate commands:

```console
uv run spotify-manager analyse-library-async
uv run spotify-manager analyse-library-sync
```

`analyse-library-async` reads only `spotify_manager/files/YourLibrary.json` and
writes `albums_total_new_async.json`, `liked_tracks_total_async.json`,
`artists_total_async.json`, and `stats_history_async.json`.

`analyse-library-sync` reads only the live Spotify API and writes the matching
`*_sync.json` files. It checkpoints every page, reconciles additions made while
the scan is running, and retries Spotify 5xx responses with capped exponential
backoff. Press `q` during a CLI retry wait to stop cleanly; rerunning the command
resumes from its checkpoint. Both modes keep JSON-lines audit logs and an undo
manifest under `spotify_manager/files/`.

The same commands are available in the web UI. Their API endpoints return a
background job that can be polled or cancelled:

```text
POST /commands/analyse-library-async
POST /commands/analyse-library-sync
GET  /commands/library-analysis-jobs/{job_id}
POST /commands/library-analysis-jobs/{job_id}/cancel
```

## Required Space secrets

| Secret | Purpose |
| --- | --- |
| `APP_PASSWORD` | Shared password for the web UI / API. |
| `SPOTIPY_CLIENT_ID` | Spotify app client id. |
| `SPOTIPY_CLIENT_SECRET` | Spotify app client secret. |
| `SPOTIPY_REDIRECT_URI` | Spotify app redirect URI. Use an explicit loopback IP for local auth, e.g. `http://127.0.0.1:8080/callback`; it must match your Spotify dashboard. |
| `SPOTIPY_CACHE_JSON` | Contents of your local `spotify_manager/auth/spotipy_token_cache.json` token file (enables headless auth). |
| `ALBUMS_TO_ADD` | App setting (integer). |
| `LIMIT` | App setting (integer). |

> This Space should be **Private** — the repository contains your personal
> library export files.
