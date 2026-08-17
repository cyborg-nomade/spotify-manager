# Deploying Spotify Manager to Hugging Face Spaces

## Deployment model

Spotify Manager runs as a private Hugging Face **Docker Space**. The container
serves `spotify_manager.web:app`, which combines the FastAPI backend, responsive
control cockpit, shared-password gate, and Genre Reveal page.

The production Space currently used by this repository is:

```text
cyborg-nomade/spotify-manager
```

The Space repository is an operational deployment target, not a blind mirror of
the GitHub repository. It contains personal source exports and can contain
routine state newer than GitHub. Normal releases therefore upload an explicit
set of changed code files while preserving and verifying all server state.

## Security requirements

- The Space must be **Private**. The repository contains Spotify library and
  Last.fm listening-history files.
- `APP_PASSWORD` must be configured. It protects the running API but does not
  protect files in a public Space repository.
- Spotify OAuth cache JSON contains refresh tokens with playlist, library, and
  follow write scopes. Store it only as a Space secret.
- Never upload `.env` or `spotify_manager/auth/spotipy_token_cache*.json` as
  repository files.
- Use a Hugging Face user token with write access only from a trusted machine.

## Container architecture

`Dockerfile` performs a lockfile-faithful, production-only `uv sync` on
`python:3.14-slim`, copies the package, switches to an unprivileged UID 1000
user, and starts `start.sh`.

`start.sh`:

1. writes each configured `*_SPOTIPY_CACHE_JSON` secret to its isolated cache
   path with mode 600;
2. warns if `APP_PASSWORD` is missing; and
3. runs Uvicorn on `0.0.0.0:${PORT:-7860}`.

The Docker working directory is
`/Users/uriel.fiori/dev/spotify-manager`, matching the established application
paths. Runtime files beneath `spotify_manager/files/` must remain writable.

## Initial Space setup

### 1. Create the Space

Create a new Space with:

| Setting | Value |
| --- | --- |
| SDK | Docker, Blank |
| Visibility | Private |
| Port | 7860, supplied by the README front matter and container |

The root `README.md` already contains the required Hugging Face metadata.

### 2. Authenticate the local Hugging Face client

```console
hf auth login
hf auth whoami
```

The token needs write access to the private Space.

### 3. Create Spotify token caches locally

Use the same Spotify credentials and exact loopback redirect URI that will be
configured in the Space:

```text
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

Register that URI in each Spotify developer application, fill the primary and
optional app credentials in `.env`, then run:

```console
just refresh-spotify-tokens
```

Complete browser authentication for every configured application. The command
creates:

```text
spotify_manager/auth/spotipy_token_cache.json
spotify_manager/auth/spotipy_token_cache_app5.json
spotify_manager/auth/spotipy_token_cache_app6.json
spotify_manager/auth/spotipy_token_cache_app7.json
spotify_manager/auth/spotipy_token_cache_app8.json
```

Each refresh token belongs to the Spotify app that issued it. Client ids and
secrets cannot share one cache.

### 4. Configure Space secrets and variables

Use **Settings -> Variables and secrets** in the Space UI. The UI is preferred
for token JSON because it avoids shell quoting and history exposure.

#### Required secrets

| Secret | Value |
| --- | --- |
| `APP_PASSWORD` | Shared password entered in the cockpit. |
| `SPOTIPY_CLIENT_ID` | Primary Spotify app client id. |
| `SPOTIPY_CLIENT_SECRET` | Primary Spotify app client secret. |
| `SPOTIPY_REDIRECT_URI` | Exact registered explicit-loopback URI. |
| `SPOTIPY_CACHE_JSON` | Full contents of the primary token cache JSON. |

For every optional app, add all three matching secrets:

```text
APP5_CLIENT_ID
APP5_CLIENT_SECRET
APP5_SPOTIPY_CACHE_JSON
```

Repeat through app8 as configured. A partial credential pair prevents client
startup; a missing cache prevents that app from authenticating headlessly.

#### Application settings

Add `ALBUMS_TO_ADD` and `LIMIT` as variables or secrets. Add every populated
playlist and Last.fm setting from
[the configuration reference](docs/CONFIGURATION.md#environment-reference).
Playlist ids reveal personal organization, so keeping them as secrets is a
reasonable default.

The Last.fm shared secret is not used and should not be deployed.

List configured names without exposing their values:

```console
hf spaces secrets list cyborg-nomade/spotify-manager
hf spaces variables list cyborg-nomade/spotify-manager
```

Any secret or variable change restarts the Space. Apply the same state snapshot
discipline used for a code deployment.

### 5. Upload the first revision

For a brand-new empty Space, upload the repository in one commit:

```console
hf upload cyborg-nomade/spotify-manager . . \
  --repo-type space \
  --commit-message "Initial Spotify Manager deployment"
```

`.env`, local OAuth caches, virtual environments, and build artifacts are
excluded. Review the file list in the Space before considering the upload
complete. A repository containing the real exports must remain private.

Do not use this whole-folder command for routine updates after the Space has
live state.

Before the first live routine, establish and test a way to retrieve runtime
state from the container. Enable Dev Mode and register an SSH key while there is
no irreplaceable runtime state, or provision persistent storage and a backup
path. Waiting until the first deployment to solve state extraction creates a
restart dependency at exactly the wrong moment.

## State-preserving update

Every Space commit, export upload, secret change, or manual restart can replace
the running container. The live container can hold state not yet present in the
Space repository. Treat deployment as a data migration, even for a CSS-only
change.

### 1. Prepare and test the GitHub branch

```console
git status -sb
just test
```

Merge the GitHub pull request before or after the Space release according to the
working agreement, but record the exact GitHub commit being deployed.

### 2. Confirm the application is idle

Do not deploy while any job is `queued`, `running`, `waiting`, or `cancelling`.
Check the cockpit and the active-job collection endpoints described in
[`docs/WEB_APP.md`](docs/WEB_APP.md#background-job-protocol).

An interactive job waiting for a choice is active. Finish or cancel it and wait
for its final state before continuing.

### 3. Snapshot live container state

The running container is authoritative after live routines have executed.
Capture its current `spotify_manager/files/` state before triggering a rebuild.

At minimum preserve every existing:

```text
*_state.json
*_log.jsonl
*_decisions.json
*_cache.json
library_analysis_*/
library_analysis_*_backups/
lastfm_history_backups/
genre_reveal_state_backups/
palace_of_memory_album_backups/
albums_total_new.json
liked_tracks_total.json
artists_total.json
stats_history.json
lastfmstats-man-et-arms.json
```

Use an already-enabled Hugging Face Dev Mode SSH session, a mounted persistent
volume, or a protected application export endpoint to copy the files to a
timestamped local directory. Check the SSH command before connecting:

```console
hf spaces ssh cyborg-nomade/spotify-manager --dry-run
hf spaces ssh cyborg-nomade/spotify-manager
```

The container project root is
`/Users/uriel.fiori/dev/spotify-manager`. Inside the SSH session, create a
timestamped archive only after the job preflight:

```console
cd /Users/uriel.fiori/dev/spotify-manager
tar -czf /tmp/spotify-manager-files-predeploy.tgz spotify_manager/files
sha256sum /tmp/spotify-manager-files-predeploy.tgz
```

Transfer it to the workstation using the connection details shown by
`hf spaces ssh ... --dry-run` and the corresponding `scp` transport.

Do not use `--auto` to enable Dev Mode immediately before a backup unless you
have confirmed that the transition will preserve the current container. A mode
change can restart the Space. If no non-restarting path to the live filesystem
exists, the release is blocked until the authoritative state is exported.

Genre Reveal also exposes a protected snapshot endpoint:

```console
curl -H 'X-App-Password: YOUR_PASSWORD' \
  https://cyborg-nomade-spotify-manager.hf.space/genre-reveal/state \
  > PREDEPLOY_DIR/genre_reveal_state.json
```

New Release Check exposes its current versioned snapshot as well. The response
contains metadata plus the state under the `state` key:

```console
curl -H 'X-App-Password: YOUR_PASSWORD' \
  https://cyborg-nomade-spotify-manager.hf.space/commands/check-new-releases-state \
  > PREDEPLOY_DIR/release_check_state_snapshot.json
```

The cockpit automatically mirrors this payload in the authenticated browser,
but an explicit deployment snapshot remains necessary in case browser site data
is cleared or deployment is performed from another device.

Validate every downloaded JSON file before using it. Record file sizes and
SHA-256 digests. Never overwrite the local copy until verification is complete.

### 4. Snapshot the Space repository revision

The repository revision is separate from the live container snapshot:

```console
hf spaces info cyborg-nomade/spotify-manager --expand sha,runtime
hf download cyborg-nomade/spotify-manager \
  --repo-type space \
  --local-dir PREDEPLOY_DIR/space-revision
```

Record the returned parent SHA. Build a manifest of every path under
`spotify_manager/files/` with size, blob id or LFS hash, and local digest. This
manifest is the invariant checked after deployment.

### 5. Reconcile state before upload

Compare the live-container snapshot, Space repository snapshot, and local
working tree:

- prefer the live-container copy for routine state changed by web runs;
- prefer intentionally newer local files only when the local command was the
  last writer;
- merge append-only logs when both sides have unique events;
- never replace a newer cursor, artist mapping, check date, or processed-id set
  with an older file; and
- keep backups from both sides until the new deployment is verified.

Stage the reconciled state in the pre-deployment directory. Do not casually copy
it over the working tree, because many files are intentionally ignored and may
contain useful local state from another execution surface.

### 6. Upload an explicit file set in one commit

Use `huggingface_hub.HfApi.create_commit` with:

- only the runtime code/assets changed by the release;
- only reconciled state files that must replace the repository copy;
- `repo_type="space"` and `revision="main"`;
- `parent_commit` set to the SHA captured in step 4; and
- `gitignore_content=""` when explicitly adding ignored state snapshots.

`parent_commit` is an optimistic lock. Abort if the Space changed after the
backup rather than committing on top of an unexamined revision.

The following template shows the production commit shape. Fill the explicit
code list, expected parent, and only the reconciled state overlays needed by
that release:

```python
from pathlib import Path

from huggingface_hub import CommitOperationAdd
from huggingface_hub import HfApi


root = Path.cwd()
repo_id = "cyborg-nomade/spotify-manager"
expected_parent = "SPACE_SHA_RECORDED_DURING_BACKUP"
code_paths = (
    "spotify_manager/api.py",
    "spotify_manager/frontend/index.html",
)
state_overlays = {
    # Remote path: validated file from the live-state snapshot.
    # "spotify_manager/files/example_state.json": Path(
    #     "/tmp/predeploy/example_state.json"
    # ),
}

api = HfApi()
current_parent = api.space_info(repo_id).sha
if current_parent != expected_parent:
    raise SystemExit(
        f"Space changed after backup: {expected_parent} -> {current_parent}"
    )

operations = [
    CommitOperationAdd(path_in_repo=path, path_or_fileobj=root / path)
    for path in code_paths
]
operations.extend(
    CommitOperationAdd(path_in_repo=path, path_or_fileobj=source)
    for path, source in state_overlays.items()
)

commit = api.create_commit(
    repo_id=repo_id,
    repo_type="space",
    revision="main",
    parent_commit=expected_parent,
    operations=operations,
    commit_message="Deploy explicit Spotify Manager update",
    gitignore_content="",
)
print(commit.commit_url)
```

Use `CommitOperationDelete` only for an intentionally removed runtime file and
list it in the deployment review. Deleting a code file does not justify a broad
remote cleanup pattern.

For a small code-only change, `hf upload` can also create a single explicit
commit without deleting other paths:

```console
hf upload cyborg-nomade/spotify-manager \
  spotify_manager/frontend/index.html \
  spotify_manager/frontend/index.html \
  --repo-type space \
  --commit-message "Deploy cockpit update"
```

However, `hf upload` does not provide the same explicit parent-revision guard.
Use the `HfApi.create_commit` approach for normal production releases and any
release carrying state.

Do not use `git push --force`, a blanket folder replacement, or a delete pattern
against `spotify_manager/files/`.

### 7. Verify repository state before the new app is trusted

For every pre-deployment state path not intentionally changed, compare the new
Space revision with the saved manifest. Path, size, blob id, and LFS digest must
remain identical. For intentionally replaced state, compare it with the
reconciled snapshot.

If the manifest differs unexpectedly, stop and roll back before running a live
routine.

### 8. Wait for build and inspect logs

```console
hf spaces wait cyborg-nomade/spotify-manager --timeout 15m
hf spaces logs cyborg-nomade/spotify-manager --build -n 200
hf spaces logs cyborg-nomade/spotify-manager -n 200
```

Startup should report one seeded token cache for every configured app and no
missing `APP_PASSWORD` warning.

### 9. Smoke test

```console
curl -fsS https://cyborg-nomade-spotify-manager.hf.space/health
curl -fsS \
  -H 'X-App-Password: YOUR_PASSWORD' \
  https://cyborg-nomade-spotify-manager.hf.space/auth/check
```

Then verify in the cockpit:

1. the Data signal board file counts and timestamps;
2. the relevant routine's persisted cursor, mapping, or pending state;
3. a live read-only library instrument;
4. a dry run of the changed routine; and
5. browser reload reconnection while a harmless dry-run job is active.

Do not make a real playlist mutation until state and dry-run output agree with
the pre-deployment expectation.

## Updating source exports

`upload-library-files-to-hf` validates and uploads `YourLibrary.json`, the
canonical Last.fm export, and the Last.fm compressed fallback parts:

```console
just upload-library-files-to-hf --dry-run
just upload-library-files-to-hf
```

Use `--your-library-only` or `--lastfm-only` when their schedules differ.

The upload creates a Space commit and therefore triggers a rebuild. Perform the
idle check and live-state snapshot first. The command preserves unrelated Space
repository paths, but it cannot by itself preserve newer files that exist only
inside the running container.

## Rollback

Keep these together for every release:

- previous Space revision SHA;
- deployed GitHub commit SHA;
- live-container state archive;
- previous Space repository download;
- before/after state manifests; and
- build and smoke-test result.

If a deployment fails:

1. Do not run a mutating routine on the failed revision.
2. Revert the Space to the previous revision through **Files and versions** or
   create a new commit containing the previous code plus the preserved current
   state.
3. Wait for the Space to run and repeat the health/auth checks.
4. Verify routine state and canonical mirrors against the pre-deployment
   manifest.
5. Restore only the specific state files proven to be missing or stale.

Avoid factory reboot as a first response. It rebuilds without cache and does not
recover uncommitted runtime files.

## Troubleshooting

### Wrong or missing password

- Confirm `APP_PASSWORD` exists as a Space secret with no accidental whitespace.
- Remember that a secret update restarts the container.
- Check `/health` first; it is public. Then call `/auth/check` with the header.
- Inspect run logs for the missing-password startup warning.

### HTTP 500 from a command

- Read the job's terminal log and Space run log.
- Verify every command-specific playlist and Last.fm setting.
- Check that the matching token cache was seeded.
- Inspect the relevant state JSON for truncation or an older incompatible shape.
- Retry with dry run after the upstream service is healthy.

### Spotify 429

- Confirm every optional app has a matching id, secret, and cache JSON.
- Look for credential-rotation messages in the job log.
- If all apps are limited, use the displayed retry time rather than repeatedly
  restarting the job.

### Spotify 500, 502, 503, 504, or connection reset

The client and long-running routines retry transient failures. Analysis backoff
starts at 10 seconds and increases to a capped delay; interactive clients expose
retry and cancellation. A cold Space can need one warm-up request. Persistent
failure is an upstream incident, not a reason to delete routine state.

### HTTP 409 after page reload

The previous job is still active. The cockpit should rediscover it through the
active-job endpoint. Do not start a duplicate. If the process restarted, inspect
the routine's durable state and begin the same command again.

### Last.fm export is invalid JSON

The deployment loader can reconstruct the large export from its compressed
base64 parts. Regenerate them with a Last.fm-only upload and verify all parts are
present in the same revision. Do not commit a Git LFS pointer as if it were JSON.

### State disappeared after deployment

Stop mutating commands. Preserve the current broken revision, retrieve the
pre-deployment live-state archive, and compare manifests. Roll back code and
restore only the proven missing state. This is why whole-folder production
uploads are prohibited after initial setup.

## Local production-equivalent run

Before deployment, run the gated application with the same startup target:

```console
uv run --env-file .env uvicorn spotify_manager.web:app \
  --host 127.0.0.1 --port 7860
```

Open `http://127.0.0.1:7860`, verify authentication, run the relevant dry run,
and check that a browser reload reconnects to its active job.
