# Deploying Spotify Manager to Hugging Face Spaces

This deploys the FastAPI backend plus the mobile web UI as a **Docker** Space,
protected by a password, using a pre-seeded Spotify OAuth token so it works with
no interactive browser login.

New files this adds to the repo:

- `spotify_manager/frontend/index.html` — the mobile UI (single file).
- `spotify_manager/web.py` — password gate + serves the UI, wrapping `api.py`
  (which is left untouched).
- `Dockerfile`, `start.sh`, `.dockerignore` — the Space build.
- `README.md` — the Space front-matter (title, `sdk: docker`, `app_port: 7860`).

Nothing in your existing application code changes, so this won't conflict with
your pending pydantic/uv PR.

---

## 1. Make the Space private (important)

Your repo contains your personal library exports (`spotify_manager/files/*.json`
— your full liked tracks, saved albums, followed artists). Anyone who can read
the Space repo can download those. **Create the Space as Private.**

The `APP_PASSWORD` gate protects the running app, but only a private repo keeps
the data files themselves out of public reach.

## 2. Create the Space

1. Go to https://huggingface.co/new-space
2. Name it (e.g. `spotify-manager`), **Space SDK: Docker → Blank**,
   **Visibility: Private**.
3. Create.

## 3. Generate your token caches (one time, on your machine)

The server can't do Spotify's interactive login. Instead it reuses the token
your local app already has. First, make sure your local `.env` uses an explicit
loopback IP redirect URI, and add that exact URI in the Spotify Developer
Dashboard:

```bash
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

Spotify rejects `localhost` redirect URIs. Authenticate or refresh every
configured Spotify app:

```bash
just refresh-spotify-tokens
```

Complete the browser login once for each app that does not already have a
cache. The command writes the primary cache plus one isolated cache for each
configured `app5` through `app8`. Each refresh token belongs to the app that
created it; client ids and secrets alone are not enough for headless rotation.

The resulting files are:

```text
spotify_manager/auth/spotipy_token_cache.json
spotify_manager/auth/spotipy_token_cache_app5.json
spotify_manager/auth/spotipy_token_cache_app6.json
spotify_manager/auth/spotipy_token_cache_app7.json
spotify_manager/auth/spotipy_token_cache_app8.json
```

Print each configured cache — you'll paste its contents into a separate Space
secret:

```bash
cat spotify_manager/auth/spotipy_token_cache.json
cat spotify_manager/auth/spotipy_token_cache_app5.json
```

It's a small JSON blob containing `access_token`, `refresh_token`, `scope`,
`expires_at`, etc. The refresh token stays valid, so the server keeps working
after the access token expires.

## 4. Set the Space secrets

In the Space → **Settings → Variables and secrets**, add these as **Secrets**:

| Name | Value |
| --- | --- |
| `APP_PASSWORD` | A password you choose (you'll type it into the web UI). |
| `SPOTIPY_CLIENT_ID` | From your local `.env`. |
| `SPOTIPY_CLIENT_SECRET` | From your local `.env`. |
| `SPOTIPY_REDIRECT_URI` | From your local `.env`; use an explicit loopback IP such as `http://127.0.0.1:8080/callback`, not `localhost`, and make sure it matches your Spotify app. |
| `SPOTIPY_CACHE_JSON` | The full contents of `spotify_manager/auth/spotipy_token_cache.json` from step 3. |
| `APP5_CLIENT_ID` ... `APP8_CLIENT_ID` | The additional Spotify app client ids configured locally. |
| `APP5_CLIENT_SECRET` ... `APP8_CLIENT_SECRET` | The matching additional Spotify app client secrets. |
| `APP5_SPOTIPY_CACHE_JSON` ... `APP8_SPOTIPY_CACHE_JSON` | The full contents of each matching `spotipy_token_cache_appN.json`. |
| `ALBUMS_TO_ADD` | From your local `.env` (an integer). |
| `LIMIT` | From your local `.env` (an integer). |

`ALBUMS_TO_ADD` and `LIMIT` can be **Variables** rather than Secrets if you
prefer; every Spotify credential and token-cache value must be a **Secret**.

> Why these names: `spotify_manager/settings.py` reads its fields from
> environment variables (pydantic-settings), so `SPOTIPY_CLIENT_ID` →
> `spotipy_client_id`, etc. No `.env` file is needed on the server.

At startup, `start.sh` recreates each configured cache. On HTTP 429, every CLI
and web command rotates from the active app to the next configured app,
force-refreshes that app's token, and retries the same Spotify request. If all
apps are rate-limited or unavailable, the existing clean pause behavior takes
over.

## 5. Push the code

The Space is its own git repo. From your project root:

```bash
# add the Space as a remote (HF gives you the exact URL on the Space page)
git remote add hf https://huggingface.co/spaces/<your-username>/spotify-manager

# push your current branch to the Space's main branch
git push hf HEAD:main
```

If your data files are large (they are — tens of MB), Hugging Face may ask you
to track them with Git LFS. If `git push` is rejected for file size:

```bash
git lfs install
git lfs track "spotify_manager/files/*.json"
git add .gitattributes && git commit -m "Track library data with LFS"
git push hf HEAD:main
```

The Space will build the Docker image and start. Watch the **Logs** tab.

## 6. Use it from your phone

Open `https://huggingface.co/spaces/<your-username>/spotify-manager` (or the
direct `*.hf.space` app URL shown on the Space page) on your phone, enter your
`APP_PASSWORD`, and you're in. Add it to your home screen for an app-like feel.

Because the Space is private, you'll need to be logged into Hugging Face on the
phone browser to open it — that's an extra layer on top of the password.

---

## What works, and what to know

- **Read-only lookups** (artist stats, album evaluation, count) work fully.
  Album evaluation uses the cached track lists when available and otherwise
  makes one live Spotify call.
- **Command buttons** run the same routines as the CLI. The ones that call
  Spotify or rewrite data files are marked ⚠ in the UI and ask for confirmation.
- **Ephemeral filesystem**: Spaces don't persist disk writes across restarts or
  rebuilds (unless you add paid persistent storage). Commands that mutate your
  actual Spotify library still take effect on Spotify; but changes written to
  the server-side JSON files are reset on the next rebuild. Re-push updated
  exports when you re-export `YourLibrary.json`.
- **Free tier sleep**: a free Space sleeps after inactivity and takes a few
  seconds to wake on the next request. The UI shows an "online/offline" dot.

## Security notes

- Keep the Space **Private**; rotate `APP_PASSWORD` if you ever shared a link.
- The `*_SPOTIPY_CACHE_JSON` tokens carry write scopes (they can modify
  playlists and follows). Treat them like passwords; they live only in Space
  secrets.
- Do not configure Spotify auth with a `localhost` redirect URI. Use an
  explicit loopback IP URI such as `http://127.0.0.1:8080/callback`.

## Running locally (optional)

The gated web app runs locally too:

```bash
APP_PASSWORD=test uv run uvicorn spotify_manager.web:app --port 8000
# open http://127.0.0.1:8000 and log in with "test"
```

Without `APP_PASSWORD` set, the gate is disabled (a warning is logged) — fine
for local dev, never for the deployed Space.
