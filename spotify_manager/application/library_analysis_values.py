"""Paths and callback types for independent resumable analysis workspaces."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Self
from typing import TypedDict
from typing import cast

from spotify_manager.domain.library_analysis_values import AnalysisMode
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key
from spotify_manager.utils.sorting import track_sort_key


type ResourceConfig = tuple[
    Path, type[LibraryModel], Callable[[LibraryModel], tuple[int, ...]]
]
type LibraryModel = YourLibraryAlbum | YourLibraryTrack | YourLibraryArtist


Echo = Callable[[str], None]
ProgressCallback = Callable[[ResourceName, int, int | None, str], None]
CancelCheck = Callable[[], bool]
Sleep = Callable[[float], None]


class ResourceState(TypedDict, total=False):
    """Annotate legacy resource progress without adding validation or serialization.

    Extra fields remain in the original mapping. Access preserves the original
    native errors for missing or malformed known fields.
    """

    status: str
    offset: int
    after: str | None
    total: object
    pages: int
    skipped: int
    stable_passes: int
    candidate_index: int
    retained: int
    source: str


class Checkpoint(TypedDict, total=False):
    """Annotate the permissive durable checkpoint without tightening its contract."""

    version: int
    mode: str
    run_id: str
    status: str
    created_at: str
    completed_at: str
    resources: dict[str, ResourceState]
    backup_dir: str
    export_fingerprint: dict[str, int]
    mirror_refresh_mode: str


@dataclass(frozen=True)
class LibraryAnalysisPaths:
    """Filesystem paths for one independent analysis output family.

    Args:
        mode: Original output family.
        files_dir: Original generated-file root.
        your_library: Original export authority.
        albums_total: Original saved-album output.
        liked_tracks_total: Original liked-track output.
        artists_total: Original followed-artist output.
        stats_history: Original statistics history output.
        checkpoint: Original durable progress location.
        staging_dir: Original resumable model workspace.
        event_log: Original audit stream.
        backups_dir: Original undo snapshots root.
    """

    mode: AnalysisMode
    files_dir: Path
    your_library: Path
    albums_total: Path
    liked_tracks_total: Path
    artists_total: Path
    stats_history: Path
    checkpoint: Path
    staging_dir: Path
    event_log: Path
    backups_dir: Path

    @classmethod
    def for_files_dir(
        cls: type[Self],
        files_dir: Path,
        mode: AnalysisMode = "sync",
    ) -> Self:
        """Build conventional paths beneath ``files_dir`` for one mode.

        Args:
            files_dir: Original root containing generated library files.
            mode: Original export, live or canonical output family.


        Returns:
            Original conventional paths for the requested output family.
        """
        workspace = files_dir / f"library_analysis_{mode}"
        suffix = "" if mode == "mirrors" else f"_{mode}"
        return cls(
            mode=mode,
            files_dir=files_dir,
            your_library=files_dir / "YourLibrary.json",
            albums_total=files_dir / f"albums_total_new{suffix}.json",
            liked_tracks_total=files_dir / f"liked_tracks_total{suffix}.json",
            artists_total=files_dir / f"artists_total{suffix}.json",
            stats_history=files_dir / f"stats_history{suffix}.json",
            checkpoint=workspace / "checkpoint.json",
            staging_dir=workspace / "staging",
            event_log=files_dir / f"library_analysis_{mode}_log.jsonl",
            backups_dir=files_dir / f"library_analysis_{mode}_backups",
        )

    def stage(self, resource: ResourceName) -> Path:
        """Return the staging path for one resource.

        Args:
            resource: Original active library resource identity.


        Returns:
            Original mode-specific staging filename for the resource.
        """
        suffix = ".json" if self.mode == "async" else ".jsonl"
        return self.staging_dir / f"{resource}{suffix}"


def scoped_paths(
    paths: LibraryAnalysisPaths, resource: ResourceName
) -> LibraryAnalysisPaths:
    """Give the original requested resource an independent resumable workspace.

    Args:
        paths: Original complete canonical output family.
        resource: Original requested resource identity.

    Returns:
        Original paths with independently scoped checkpoint and staging.
    """
    workspace = paths.checkpoint.parent / resource
    return replace(
        paths,
        checkpoint=workspace / "checkpoint.json",
        staging_dir=workspace / "staging",
    )


def resource_config(
    paths: LibraryAnalysisPaths, resource: ResourceName
) -> ResourceConfig:
    """Select the original resource-specific output, model and ordering rule.

    Args:
        paths: Original complete canonical output family.
        resource: Original requested resource, with the original artist fallback.

    Returns:
        Original compatible path, model constructor and ordering rule.
    """
    config: tuple[Path, object, object]
    if resource == "albums":
        config = (paths.albums_total, YourLibraryAlbum, album_sort_key)
    elif resource == "tracks":
        config = (paths.liked_tracks_total, YourLibraryTrack, track_sort_key)
    else:
        config = (paths.artists_total, YourLibraryArtist, artist_sort_key)
    return cast(ResourceConfig, config)
