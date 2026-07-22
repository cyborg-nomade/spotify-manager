#!/usr/bin/env bash
# Container entry point for Hugging Face Spaces.
#
# Seeds the Spotify OAuth token cache from a secret (so spotipy can refresh
# tokens headlessly, with no interactive browser login) and then starts the
# gated web app on the port Spaces expects (7860).
set -euo pipefail

# Each Spotify app has its own refresh token and cache. Recreate configured
# caches from Space secrets before starting the headless server.
seed_spotify_cache() {
  local label="$1"
  local cache_json_var="$2"
  local cache_path="$3"
  local cache_json="${!cache_json_var-}"

  if [ -n "${cache_json}" ]; then
    mkdir -p "$(dirname "${cache_path}")"
    printf '%s' "${cache_json}" > "${cache_path}"
    chmod 600 "${cache_path}"
    echo "start.sh: seeded Spotify token cache for ${label}"
  else
    echo "start.sh: ${cache_json_var} not set; ${label} cannot be used headlessly."
  fi
}

SPOTIPY_CACHE_PATH="${SPOTIPY_CACHE_PATH:-spotify_manager/auth/spotipy_token_cache.json}"
export SPOTIPY_CACHE_PATH
seed_spotify_cache "primary" "SPOTIPY_CACHE_JSON" "${SPOTIPY_CACHE_PATH}"

for app_number in 5 6 7 8; do
  label="app${app_number}"
  client_id_var="APP${app_number}_CLIENT_ID"
  client_secret_var="APP${app_number}_CLIENT_SECRET"
  cache_json_var="APP${app_number}_SPOTIPY_CACHE_JSON"
  cache_path_var="APP${app_number}_SPOTIPY_CACHE_PATH"
  cache_path="spotify_manager/auth/spotipy_token_cache_${label}.json"
  if [ -n "${!cache_path_var-}" ]; then
    cache_path="${!cache_path_var}"
  fi
  printf -v "${cache_path_var}" '%s' "${cache_path}"
  export "${cache_path_var}"

  if [ -n "${!client_id_var-}" ] || [ -n "${!client_secret_var-}" ]; then
    seed_spotify_cache "${label}" "${cache_json_var}" "${cache_path}"
  fi
done

if [ -z "${APP_PASSWORD:-}" ]; then
  echo "start.sh: WARNING — APP_PASSWORD is not set; the password gate is DISABLED."
fi

exec uvicorn spotify_manager.web:app --host 0.0.0.0 --port "${PORT:-7860}"
