"""Replay original runs through independently constructed analysis dependencies."""

from dataclasses import dataclass
from functools import partial
from typing import Literal
from typing import cast

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.application import library_analysis_checkpoint as checkpoints
from spotify_manager.application import library_analysis_run as workflow
from spotify_manager.application.library_analysis_effects import AnalysisCatalog
from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_effects import OffsetRead
from spotify_manager.application.library_analysis_publication import AnalysisPublication
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import resource_config
from spotify_manager.application.library_analysis_values import scoped_paths
from spotify_manager.domain.library_analysis_values import LibraryAnalysisCancelledError
from spotify_manager.domain.library_analysis_values import LibrarySyncSummary
from spotify_manager.domain.library_analysis_values import MirrorRefreshMode
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import (
    _FollowedArtistsEndpointUnavailableError,
)
from spotify_manager.infrastructure import library_analysis_backups as backups
from spotify_manager.infrastructure import library_analysis_files as codecs
from spotify_manager.infrastructure.library_analysis_errors import AnalysisFailure
from spotify_manager.infrastructure.library_analysis_retry import LibraryRetry
from spotify_manager.infrastructure.library_models import album_from_saved_item
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from spotify_manager.routines import analyse_library as legacy
from tests.support import library_analysis_run as original
from tests.support.effects import Fault


@dataclass(frozen=True)
class MemoryCatalog:
    """Supply original mutable fake authority without invoking a production client.

    Args:
        edge: Original input facts and complete accepted effect observations.
    """

    edge: original.AnalysisObservations

    def offset(self, resource: ResourceName, initial: bool) -> OffsetRead:
        """Select original fake saved-resource facts at the requested boundary.

        Args:
            resource: Original saved-resource identity.
            initial: Original monotonic-versus-reconciliation phase.

        Returns:
            Original fake authority's explicit page reader.
        """
        if resource == "albums":
            return cast(OffsetRead, self.edge.spotify.current_user_saved_albums)
        return cast(OffsetRead, self.edge.spotify.current_user_saved_tracks)

    def artists(self, after: str | None) -> object:
        """Retain original immediate 502 fallback for the initial cursor scan.

        Args:
            after: Original stored cursor or none.

        Returns:
            Original fake cursor page.

        Raises:
            _FollowedArtistsEndpointUnavailableError: Original immediate 502 fallback.
        """
        try:
            return self.edge.spotify.current_user_followed_artists(
                limit=10, after=after
            )
        except SpotifyException as exc:
            if exc.http_status == 502:
                raise _FollowedArtistsEndpointUnavailableError(
                    "the followed-artists endpoint returned HTTP 502"
                ) from exc
            raise

    def reconcile_artists(self, after: str | None) -> object:
        """Supply original complete fake artist reconciliation facts.

        Args:
            after: Original current pass cursor or none.

        Returns:
            Original unvalidated fake cursor page.
        """
        return self.edge.spotify.current_user_followed_artists(limit=10, after=after)

    def following(self, identities: list[str]) -> object:
        """Supply original fake candidate verification authority.

        Args:
            identities: Original ordered complete candidate batch.

        Returns:
            Original fake live follow statuses.
        """
        return self.edge.spotify.current_user_following_artists(identities)


def _files() -> AnalysisFiles:
    # These substituted boundary callbacks record their original nested read/write
    # effects. No production facade runner or composition factory is invoked.
    return AnalysisFiles(
        legacy.load_json,
        legacy.write_json_atomic,
        legacy.load_model_list,
        legacy.load_models_jsonl,
        legacy.write_models,
        legacy.append_models_jsonl,
        legacy.append_event,
        legacy.load_your_library,
        legacy.utc_now,
        legacy.new_run_id,
        legacy.export_fingerprint,
        codecs.reset_staging,
        codecs.remove,
        legacy.latest_export_artists,
    )


def _publication(files: AnalysisFiles) -> AnalysisPublication:
    return AnalysisPublication(
        partial(backups.create_backup_manifest, files=files),
        partial(backups.create_live_mirror_backup_manifest, files=files),
        partial(backups.create_resource_backup, files=files),
        partial(backups.pre_analysis_stats_history, files=files),
        legacy.current_stats_history_key,
        backups.manifest_summaries,
        backups.resource_manifest_summary,
        resource_config,
    )


def _paths(edge: original.AnalysisObservations, kind: str) -> LibraryAnalysisPaths:
    paths = original._paths(edge.root, kind)
    if kind in {"albums", "tracks", "artists"}:
        return scoped_paths(paths, cast(ResourceName, kind))
    return paths


def _run(
    edge: original.AnalysisObservations, kind: str, full: bool
) -> LibrarySyncSummary:
    files = _files()
    paths = _paths(edge, kind)
    refresh: MirrorRefreshMode | None = None
    if paths.mode == "mirrors":
        refresh = "full" if full else "incremental"
    checkpoint = checkpoints.load_or_create_checkpoint(files, paths, refresh)
    memory = MemoryCatalog(edge)
    catalog = AnalysisCatalog(
        memory.offset,
        memory.artists,
        memory.reconcile_artists,
        memory.following,
        album_from_saved_item,
        codecs.track_from_saved_item,
        codecs.artist_from_api_item,
        codecs.page_items,
        codecs.followed_artist_page_items,
    )
    retry = LibraryRetry(
        paths, checkpoint, files, edge.echo, edge.wait, edge.sleep, 0, 0
    )
    progress = None if edge.profile == "no-progress" else edge.progress
    session = AnalysisSession(
        paths, checkpoint, files, catalog, retry.call, edge.echo, progress, edge.cancel
    )
    return _invoke(session, _publication(files), kind, full)


def _invoke(
    session: AnalysisSession, publication: AnalysisPublication, kind: str, full: bool
) -> LibrarySyncSummary:
    label = f"Live {kind} mirror refresh failed"
    if kind in {"export", "sync", "mirrors"}:
        label = {
            "export": "Export analysis failed",
            "sync": "Live analysis failed",
            "mirrors": "Live mirror refresh failed",
        }[kind]
    paused: tuple[type[BaseException], ...] = (
        LibraryAnalysisCancelledError,
        KeyboardInterrupt,
    )
    if kind != "export":
        paused = (*paused, SpotifyRateLimitError)
    with AnalysisFailure(session, label, paused):
        return _complete(session, publication, kind, full)


def _complete(
    session: AnalysisSession, publication: AnalysisPublication, kind: str, full: bool
) -> LibrarySyncSummary:
    if kind == "export":
        return workflow.analyse_export(session, publication)
    if kind == "sync":
        return workflow.analyse_live(session, publication)
    if kind == "mirrors":
        return workflow.refresh_mirrors(session, publication, full)
    return workflow.refresh_resource(
        session, publication, cast(ResourceName, kind), full
    )


@pytest.mark.parametrize("case", original.cases())
def test_injected_analysis_matches_original_complete_effects(
    case: dict[str, object],
) -> None:
    """Preserve complete original runs and restart prefixes with explicit dependencies.

    Args:
        case: Immutable original complete input and effect observations.
    """
    fault = cast(dict[str, object] | None, case["fault"])
    interruption = (
        None
        if fault is None
        else Fault(
            cast(str, fault["operation"]),
            cast(Literal["before", "after"], fault["phase"]),
            cast(int, fault["occurrence"]),
        )
    )
    assert (
        original.outcome(
            cast(str, case["kind"]),
            cast(str, case["profile"]),
            cast(bool, case["full"]),
            interruption,
            cast(bool, case["resume"]),
            _run,
        )
        == case["outcome"]
    )
