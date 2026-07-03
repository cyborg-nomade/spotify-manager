#!/usr/bin/env bash
# Container entry point for Hugging Face Spaces.
#
# Seeds the Spotify OAuth token cache from a secret (so spotipy can refresh
# tokens headlessly, with no interactive browser login) and then starts the
# gated web app on the port Spaces expects (7860).
set -euo pipefail

# Spotipy caches its OAuth token in ".cache" in the working directory. On a
# fresh container there is none, so recreate it from the SPOTIPY_CACHE_JSON
# secret. The refresh token inside stays valid across restarts; spotipy uses it
# to mint new access tokens automatically.
if [ -n "${SPOTIPY_CACHE_JSON:-}" ]; then
  printf '%s' "${SPOTIPY_CACHE_JSON}" > "${PWD}/.cache"
  echo "start.sh: seeded Spotify token cache from SPOTIPY_CACHE_JSON"
else
  echo "start.sh: SPOTIPY_CACHE_JSON not set — live Spotify calls will fail until it is."
fi

if [ -z "${APP_PASSWORD:-}" ]; then
  echo "start.sh: WARNING — APP_PASSWORD is not set; the password gate is DISABLED."
fi

exec uvicorn spotify_manager.web:app --host 0.0.0.0 --port "${PORT:-7860}"
