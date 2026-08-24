"""Runtime construction and managed-path helpers for shared library data."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from spotify_manager.core.library_data.models import ALL_ARTIFACTS
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataConfigurationError
from spotify_manager.core.library_data.models import LibraryDataError
from spotify_manager.core.library_data.service import ArtifactStatus
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.core.library_data.store import LibraryDataStore
from spotify_manager.infrastructure.huggingface.library_data_store import (
    HubLibraryDataStore,
)
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)


DEFAULT_LIBRARY_DATA_REPO = "cyborg-nomade/spotify-manager-data"
DEFAULT_LIBRARY_DATA_MANIFEST = "manifest.json"
FILES_DIR = Path(__file__).resolve().parents[2] / "files"
DEFAULT_LIBRARY_DATA_LOCAL_ROOT = FILES_DIR / "library_data_store"
DEFAULT_ARTIFACT_PATHS: dict[ArtifactName, Path] = {
    "albums": FILES_DIR / "albums_total_new.json",
    "tracks": FILES_DIR / "liked_tracks_total.json",
    "artists": FILES_DIR / "artists_total.json",
    "scrobbles": FILES_DIR / "lastfmstats-man-et-arms.json",
}
_PATH_TO_ARTIFACT = {
    path.resolve(): name for name, path in DEFAULT_ARTIFACT_PATHS.items()
}
_logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_library_data_service() -> LibraryDataService:
    """Return the configured process-wide durable data service."""
    backend = os.environ.get("SPOTIFY_MANAGER_DATA_BACKEND", "hub").casefold()
    manifest = os.environ.get(
        "SPOTIFY_MANAGER_DATA_MANIFEST",
        DEFAULT_LIBRARY_DATA_MANIFEST,
    )
    store: LibraryDataStore
    if backend == "local":
        root = Path(
            os.environ.get(
                "SPOTIFY_MANAGER_DATA_LOCAL_ROOT",
                str(DEFAULT_LIBRARY_DATA_LOCAL_ROOT),
            )
        )
        store = JsonLibraryDataStore(root, manifest_filename=manifest)
    elif backend == "hub":
        repo_id = os.environ.get(
            "SPOTIFY_MANAGER_DATA_REPO",
            DEFAULT_LIBRARY_DATA_REPO,
        )
        token = (
            os.environ.get("SPOTIFY_MANAGER_DATA_TOKEN")
            or os.environ.get("SPOTIFY_MANAGER_STATE_TOKEN")
            or os.environ.get("HF_TOKEN")
        )
        store = HubLibraryDataStore(
            repo_id,
            manifest_filename=manifest,
            token=token,
        )
    else:
        raise LibraryDataConfigurationError(
            "SPOTIFY_MANAGER_DATA_BACKEND must be 'hub' or 'local'."
        )
    return LibraryDataService(store, DEFAULT_ARTIFACT_PATHS)


def reset_library_data_service() -> None:
    """Clear the runtime singleton after tests or configuration changes."""
    get_library_data_service.cache_clear()


def artifact_for_path(path: Path) -> ArtifactName | None:
    """Return the managed artifact represented by an exact canonical path."""
    return _PATH_TO_ARTIFACT.get(path.resolve())


def publish_managed_path(path: Path, *, source: str) -> bool:
    """Publish ``path`` when it is one of the four canonical artifacts."""
    artifact = artifact_for_path(path)
    if artifact is None:
        return False
    get_library_data_service().publish(artifact, source=source)
    return True


def hydrate_runtime_library_data(
    *,
    strict: bool = False,
) -> tuple[ArtifactStatus, ...]:
    """Hydrate all managed files, optionally tolerating an unavailable store."""
    try:
        return get_library_data_service().hydrate_all()
    except LibraryDataError:
        if strict:
            raise
        _logger.warning(
            "Could not hydrate durable library data; using local fallback files.",
            exc_info=True,
        )
        return tuple(
            ArtifactStatus(
                name=name,
                filename=DEFAULT_ARTIFACT_PATHS[name].name,
                exists=DEFAULT_ARTIFACT_PATHS[name].exists(),
                updated_at=None,
                size_bytes=None,
                sha256=None,
                source=None,
                local_current=False,
            )
            for name in ALL_ARTIFACTS
        )
