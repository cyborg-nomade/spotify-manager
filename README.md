---
title: Spotify Manager
emoji: 🎧
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Personal Spotify library manager — mobile web UI over a FastAPI backend.
---

# Spotify Manager

A small mobile-first web UI over the Spotify Manager FastAPI backend, so the
library lookups and maintenance commands are usable from a phone.

This Space runs the app defined in `spotify_manager/web.py` (the pure API lives
in `spotify_manager/api.py`). It is protected by a shared password and talks to
Spotify with a pre-seeded OAuth token.

See **DEPLOY.md** for full setup: required secrets, how to generate the token
cache, and security notes.

## Required Space secrets

| Secret | Purpose |
| --- | --- |
| `APP_PASSWORD` | Shared password for the web UI / API. |
| `SPOTIPY_CLIENT_ID` | Spotify app client id. |
| `SPOTIPY_CLIENT_SECRET` | Spotify app client secret. |
| `SPOTIPY_REDIRECT_URI` | Spotify app redirect URI (must match your Spotify dashboard). |
| `SPOTIPY_CACHE_JSON` | Contents of your local `.cache` token file (enables headless auth). |
| `ALBUMS_TO_ADD` | App setting (integer). |
| `LIMIT` | App setting (integer). |

> This Space should be **Private** — the repository contains your personal
> library export files.
