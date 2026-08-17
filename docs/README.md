# Project Documentation

Spotify Manager is a personal automation application for maintaining a Spotify
library and carrying out the listening routines defined in
[`THE RULES OF MUSIC LISTENING.md`](../THE%20RULES%20OF%20MUSIC%20LISTENING.md).
The same Python routine layer is exposed through a Typer CLI, a FastAPI service,
and a responsive web cockpit.

## Reading paths

### Running the project

1. Read [Configuration](CONFIGURATION.md).
2. Follow the [README command reference](../README.md#library-mirror-commands).
3. For the browser interface, read [Web application and API](WEB_APP.md).

### Understanding or changing the project

1. Read [Architecture](ARCHITECTURE.md).
2. Read [Data and state](DATA_AND_STATE.md) before touching anything under
   `spotify_manager/files/`.
3. Use the routine-specific section in the [README](../README.md) together with
   the corresponding module under `spotify_manager/routines/`.
4. Run the quality checks documented in
   [Architecture: development workflow](ARCHITECTURE.md#development-workflow).

### Operating the Hugging Face Space

1. Read [Data and state](DATA_AND_STATE.md), especially the state ownership
   rules.
2. Follow [DEPLOY.md](../DEPLOY.md) for initial setup or a state-preserving
   release.
3. Use the Space logs and health endpoint for post-deployment verification.

## Documentation map

| Document | Primary audience | Purpose |
| --- | --- | --- |
| [`README.md`](../README.md) | Users and operators | Quick start and detailed CLI routine reference. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Maintainers | System context, layers, execution paths, integrations, and extension points. |
| [`CONFIGURATION.md`](CONFIGURATION.md) | Users and operators | Dependencies, credentials, settings, local authentication, and startup commands. |
| [`DATA_AND_STATE.md`](DATA_AND_STATE.md) | Operators and maintainers | File taxonomy, source-of-truth hierarchy, persistence, backups, and recovery. |
| [`WEB_APP.md`](WEB_APP.md) | Web users and API clients | Web authentication, background-job protocol, endpoint groups, and local use. |
| [`DEPLOY.md`](../DEPLOY.md) | Operators | Private Hugging Face Space deployment and rollback runbook. |
| [`THE RULES OF MUSIC LISTENING.md`](../THE%20RULES%20OF%20MUSIC%20LISTENING.md) | Product owner and maintainers | Behavioral rules implemented by the playlist routines. |

## Glossary

| Term | Meaning |
| --- | --- |
| Source export | A file produced outside the app, notably `YourLibrary.json` or the Last.fm scrobble export. |
| Canonical mirror | The app's current local representation of live Spotify albums, tracks, artists, and statistics. |
| Analysis output | An explicitly suffixed `*_async.json` or `*_sync.json` result used for comparison and recovery. |
| Routine state | A restart-safe cursor, mapping, pending choice, or active-run snapshot. |
| Audit log | An append-only `.jsonl` record of decisions and Spotify mutations. |
| Dry run | A preview that avoids playlist or library mutations. A few routines deliberately persist safe metadata such as artist mappings or refreshed scrobbles; their README sections call this out. |
| Interactive job | A web background job that may pause for a choice and resume through a choice endpoint. |
| Live server state | Runtime files currently held by the deployed Space. They can be newer than both GitHub and the Space repository revision. |
