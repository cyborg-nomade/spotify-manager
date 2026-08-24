# Deploying Spotify Manager to Hugging Face Spaces

## Deployment model

Spotify Manager runs as the private Docker Space
`cyborg-nomade/spotify-manager`. Uvicorn serves `spotify_manager.web:app`, which
combines the FastAPI backend, password gate, control cockpit, and Genre Reveal.

Durable routine state and canonical data are independent of the Space container
and repository. `state.json` lives in `cyborg-nomade/spotify-manager-state`;
compressed Spotify mirrors and Last.fm history live in
`cyborg-nomade/spotify-manager-data`. Local CLI, local web, and the Space use
the same services.

Three assets therefore have separate lifecycles:

1. code and packaged data in the Space repository;
2. durable routine state in the private state dataset;
3. durable canonical files in the private library-data dataset; and
4. container-local logs, caches, backups, and analysis staging.

Deployments replace the first asset, must never overwrite the second or third,
and may replace the fourth unless it is explicitly copied or committed.

## Security requirements

- Keep the Space and both datasets private.
- Configure `APP_PASSWORD`; it gates the running API.
- Configure a separate `AUTOMATION_TOKEN` for unattended API calls.
- Store Spotify client secrets and OAuth cache JSON only as Space secrets.
- Store a write-capable HF token as `SPOTIFY_MANAGER_STATE_TOKEN` so the Space
  can update the private state dataset.
- Store a write-capable HF token as `SPOTIFY_MANAGER_DATA_TOKEN` so the Space
  can update the private canonical-file dataset.
- Never upload `.env` or `spotify_manager/auth/spotipy_token_cache*.json`.
- Treat exported state, mirrors, audit logs, and Last.fm history as private.

## Container architecture

`Dockerfile` performs a lockfile-faithful production `uv sync` on Python 3.14,
copies the package, switches to unprivileged UID 1000, and starts `start.sh`.
Startup writes each configured `*_SPOTIPY_CACHE_JSON` secret to its isolated
mode-600 cache and starts Uvicorn on `0.0.0.0:${PORT:-7860}`.

The working directory is `/Users/uriel.fiori/dev/spotify-manager`. Files under
`spotify_manager/files/` are writable but remain container-local unless they
are uploaded elsewhere.

## Initial setup

### 1. Create private repositories

Create a private Docker Space and private dataset:

```console
hf repos create cyborg-nomade/spotify-manager \
  --repo-type space --space-sdk docker --private
hf repos create cyborg-nomade/spotify-manager-state \
  --repo-type dataset --private
hf repos create cyborg-nomade/spotify-manager-data \
  --repo-type dataset --private
```

The state dataset contains exactly one application-owned file, `state.json`.
The library-data dataset contains `manifest.json` and compressed artifacts.
Seed the latter from reviewed canonical files before enabling automatic
publication:

```console
just library-data-push --yes
just library-data-status
```

### 2. Authenticate locally

```console
hf auth login
hf auth whoami
```

The token needs write access to both private repositories. The default local
state backend uses this cached token unless `SPOTIFY_MANAGER_STATE_TOKEN` is set.

### 3. Prepare Spotify OAuth caches

Register the exact loopback redirect URI in every Spotify application:

```text
http://127.0.0.1:8080/callback
```

Fill the primary and optional app credentials in `.env`, then run:

```console
just refresh-spotify-tokens
```

Each refresh token belongs to its issuing app. Do not combine one cache with a
different client id or secret.

### 4. Configure Space secrets

Required operational secrets are:

| Secret | Purpose |
| --- | --- |
| `APP_PASSWORD` | Password entered in the cockpit. |
| `AUTOMATION_TOKEN` | High-entropy token shared only with GitHub Actions. |
| `SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET` | Primary Spotify app. |
| `SPOTIPY_REDIRECT_URI` | Exact registered loopback URI. |
| `SPOTIPY_CACHE_JSON` | Complete primary OAuth cache. |
| `SPOTIFY_MANAGER_STATE_TOKEN` | HF token with state-dataset read/write access. |
| `SPOTIFY_MANAGER_DATA_TOKEN` | HF token with library-data read/write access. |

The GitHub repository needs these Actions secrets:

| Secret | Purpose |
| --- | --- |
| `HF_SPACE_TOKEN` | Read access to the private Space. |
| `AUTOMATION_TOKEN` | Must exactly match the Space secret. |

For app5 through app8, configure each complete client-id, client-secret, and
cache triplet. Add the playlist and Last.fm settings listed in
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

The state repository and filename have working defaults. Override them only
when intentionally moving the shared state:

```text
SPOTIFY_MANAGER_STATE_BACKEND=hub
SPOTIFY_MANAGER_STATE_REPO=cyborg-nomade/spotify-manager-state
SPOTIFY_MANAGER_STATE_FILENAME=state.json
```

List secret names without exposing values:

```console
hf spaces secrets list cyborg-nomade/spotify-manager
```

Changing a secret restarts the Space, but routine state remains in the dataset.

## Nightly refresh schedule

`.github/workflows/nightly-library-refresh.yml` starts daily at 22:17 UTC,
which is 23:17 in Berlin winter time and 00:17 in summer time. The client uses
the Europe/Berlin timezone for its hard 05:00 deadline. It runs these jobs
sequentially:

1. update Last.fm scrobble history;
2. refresh the incremental albums mirror;
3. refresh the incremental liked-tracks mirror; and
4. refresh the incremental artists mirror.

The odd start minute avoids GitHub's busiest scheduling boundary. The workflow
reconnects to an existing matching job after overlap, retries Space wake-up and
gateway failures, and resumes analysis checkpoints after a Space restart. A
Spotify rate-limit pause ends the run successfully so the next night can
continue. At the deadline it requests cancellation at the next durable
boundary. GitHub's `workflow_dispatch` entry provides a manual Run workflow
button without changing the schedule.

## Deploying an update

### 1. Verify the branch

```console
git status -sb
just test
```

Record the GitHub commit or branch being deployed. Do not deploy with an active
playlist mutation job; finish or cancel it first.

### 2. Export state independently

An export is not required for ordinary deployment, but it provides a readable
operator snapshot:

```console
just state-show
just state-export /tmp/spotify-manager-state-predeploy.json
```

Confirm the dataset revision from the CLI matches the cockpit Data Signal Board.
Do not add the exported snapshot to the Space upload.

### 3. Preserve container-local data when needed

Code deployment does not preserve newer container-local mirrors, logs, caches,
analysis checkpoints, or source exports. Before a deployment that must retain
them, copy or commit the specific paths. Important examples include:

```text
albums_total_new.json
liked_tracks_total.json
artists_total.json
stats_history.json
lastfmstats-man-et-arms.json
*_log.jsonl
*_cache.json
library_analysis_*/
library_analysis_*_backups/
lastfm_history_backups/
palace_of_memory_album_backups/
```

Routine `*_state.json` and `*_decisions.json` files are legacy migration inputs,
not production state overlays. Never use them to replace the dataset.

### 4. Upload an explicit code set

The Space is an operational target containing personal data, so routine updates
should upload only intended changed files in one commit. A typical code-only
release uses `HfApi.create_commit` with the current Space SHA as `parent_commit`
and a list of `CommitOperationAdd` operations.

For a repository-wide first upload only:

```console
hf upload cyborg-nomade/spotify-manager . . \
  --repo-type space \
  --commit-message "Initial Spotify Manager deployment"
```

Do not use that broad command for normal updates. Never upload `.env`, OAuth
caches, an exported central state snapshot, or unrelated local generated files.

### 5. Wait and verify

```console
hf spaces wait cyborg-nomade/spotify-manager --timeout 900
hf spaces logs cyborg-nomade/spotify-manager
```

Then verify:

1. `/health` returns `{"status":"ok"}`;
2. the password gate unlocks;
3. the Data Signal Board shows the shared state timestamp and namespace count;
4. View opens the guided namespace editor, Advanced JSON remains available,
   and Export downloads a revisioned snapshot;
5. local `just state-show` reports the same dataset revision;
6. active-job endpoints reconnect correctly after a page reload; and
7. one representative dry run reaches Spotify without an opaque HTTP 500.

## Updating source exports

Use the dedicated command for Spotify and Last.fm source files:

```console
just upload-library-files-to-hf --dry-run
just upload-library-files-to-hf
```

This command is unrelated to central state. Validate the item counts and sizes
before applying the upload.

## Rollback

Code and state roll back independently.

- For a code regression, restore or redeploy the previous Space repository
  revision. The state dataset remains current.
- For a bad state edit, inspect the private dataset commit history, export the
  desired revision, and apply it with `state-edit --force` after stopping active
  routines.
- For lost container-local mirrors or logs, restore only the affected files from
  the pre-deployment copy or analysis backup.

Never roll back all three assets together unless each has independently been
proved wrong.

## Troubleshooting

### Wrong or missing password

Confirm `APP_PASSWORD` exists in Space secrets. Secret changes restart the
container. The browser sends it as `X-App-Password`.

### Shared state is unavailable

Check that `SPOTIFY_MANAGER_STATE_TOKEN` exists and can read/write
`cyborg-nomade/spotify-manager-state`. Confirm the dataset is private and still
contains valid `state.json`. The API returns HTTP 503 for inaccessible state and
HTTP 409 for concurrent edits.

### State changed elsewhere

Another local or web process committed the same namespace after it was loaded.
Reload the state and retry. Do not use `--force` merely to bypass a conflict.

### Spotify 429 or 5xx

429 handling rotates configured Spotify credentials and honors Retry-After.
Transient 500/502/503/504 and connection resets use bounded retries. A cold
Space can need one warm-up request; repeated failure is an upstream or credential
incident, not a reason to clear shared state.

### HTTP 409 after page reload

The routine is already active or has a saved pending interaction. Reconnect to
the returned job when possible; after a process restart, run the command again
so it resumes from its central namespace.

## Local production-equivalent run

```console
uv run uvicorn spotify_manager.web:app --host 127.0.0.1 --port 8765
```

By default this uses the same private Hub state as production. For isolated
development only:

```console
SPOTIFY_MANAGER_STATE_BACKEND=local \
SPOTIFY_MANAGER_STATE_LOCAL_PATH=/tmp/spotify-manager-state.json \
uv run uvicorn spotify_manager.web:app --host 127.0.0.1 --port 8765
```
