"""Replay original runs through independently constructed analysis dependencies."""

from dataclasses import dataclass
from typing import Literal
from typing import cast

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.application import library_analysis_checkpoint as checkpoints
from spotify_manager.application import library_analysis_run as workflow
from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_effects import OffsetRead
from spotify_manager.application.library_analysis_publication import AnalysisPublication
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.application.library_analysis_values import scoped_paths
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.library_analysis_values import LibraryAnalysisCancelledError
from spotify_manager.domain.library_analysis_values import LibrarySyncSummary
from spotify_manager.domain.library_analysis_values import MirrorRefreshMode
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import (
    _FollowedArtistsEndpointUnavailableError,
)
from spotify_manager.infrastructure import library_analysis_files as codecs
from spotify_manager.infrastructure.library_analysis_catalog import SpotifyOffsetPages
from spotify_manager.infrastructure.library_analysis_errors import AnalysisFailure
from spotify_manager.infrastructure.library_analysis_retry import LibraryRetry
from spotify_manager.infrastructure.library_analysis_storage import AnalysisStorage
from spotify_manager.infrastructure.library_models import album_from_saved_item
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from tests.support import library_analysis_run as original
from tests.support.analysis_dependencies import RecordedAnalysisBackups
from tests.support.analysis_dependencies import observed_analysis_files
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
        return SpotifyOffsetPages(cast(Spotify, self.edge.spotify), resource, initial)

    async def artists(self, after: str | None) -> object:
        """Retain original immediate 502 fallback for the initial cursor scan.

        Args:
            after: Original stored cursor or none.

        Returns:
            Original fake cursor page.

        Raises:
            _FollowedArtistsEndpointUnavailableError: Original immediate 502 fallback.
        """
        try:
            return await self.edge.spotify.current_user_followed_artists(
                limit=10, after=after
            )
        except SpotifyException as exc:
            if exc.http_status == 502:
                raise _FollowedArtistsEndpointUnavailableError(
                    "the followed-artists endpoint returned HTTP 502"
                ) from exc
            raise

    async def reconcile_artists(self, after: str | None) -> object:
        """Supply original complete fake artist reconciliation facts.

        Args:
            after: Original current pass cursor or none.

        Returns:
            Original unvalidated fake cursor page.
        """
        return await self.edge.spotify.current_user_followed_artists(
            limit=10, after=after
        )

    async def following(self, identities: list[str]) -> object:
        """Supply original fake candidate verification authority.

        Args:
            identities: Original ordered complete candidate batch.

        Returns:
            Original fake live follow statuses.
        """
        return await self.edge.spotify.current_user_following_artists(identities)

    def convert(self, row: object, resource: ResourceName) -> LibraryModel | None:
        """Decode a saved resource row without configurable parsing callbacks.

        Args:
            row: Unvalidated transport row.
            resource: Active resource.

        Returns:
            Accepted model, or none for an unusable row.
        """
        if resource == "albums":
            return album_from_saved_item(row)
        if resource == "tracks":
            return codecs.track_from_saved_item(row)
        return codecs.artist_from_api_item(row)

    def items(self, page: object, resource: ResourceName) -> list[object]:
        """Validate a saved-resource response.

        Args:
            page: Unvalidated response.
            resource: Active resource.

        Returns:
            Complete raw rows.
        """
        return codecs.page_items(page, resource)

    def artist_items(self, page: object) -> tuple[list[object], dict[str, object]]:
        """Validate a followed-artists response.

        Args:
            page: Unvalidated response.

        Returns:
            Complete raw rows and cursor envelope.
        """
        return codecs.followed_artist_page_items(page)


def _publication() -> AnalysisPublication:
    return RecordedAnalysisBackups(AnalysisStorage())


def _paths(edge: original.AnalysisObservations, kind: str) -> LibraryAnalysisPaths:
    paths = original._paths(edge.root, kind)
    if kind in {"albums", "tracks", "artists"}:
        return scoped_paths(paths, cast(ResourceName, kind))
    return paths


async def _run(
    edge: original.AnalysisObservations, kind: str, full: bool
) -> LibrarySyncSummary:
    files = observed_analysis_files()
    paths = _paths(edge, kind)
    refresh: MirrorRefreshMode | None = None
    if paths.mode == "mirrors":
        refresh = "full" if full else "incremental"
    checkpoint = await checkpoints.load_or_create_checkpoint(files, paths, refresh)
    catalog = MemoryCatalog(edge)
    retry = LibraryRetry(paths, checkpoint, files, edge, edge, edge, 0, 0)
    progress = None if edge.profile == "no-progress" else edge
    session = AnalysisSession(
        paths, checkpoint, files, catalog, retry, edge, progress, edge
    )
    return await _invoke(session, RecordedAnalysisBackups(files.source), kind, full)


async def _invoke(
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
    async with AnalysisFailure(session, label, paused):
        return await _complete(session, publication, kind, full)


async def _complete(
    session: AnalysisSession, publication: AnalysisPublication, kind: str, full: bool
) -> LibrarySyncSummary:
    if kind == "export":
        return await workflow.analyse_export(session, publication)
    if kind == "sync":
        return await workflow.analyse_live(session, publication)
    if kind == "mirrors":
        return await workflow.refresh_mirrors(session, publication, full)
    return await workflow.refresh_resource(
        session, publication, cast(ResourceName, kind), full
    )


@pytest.mark.parametrize("case", original.cases())
async def test_injected_analysis_matches_original_complete_effects(
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
        await original.outcome(
            cast(str, case["kind"]),
            cast(str, case["profile"]),
            cast(bool, case["full"]),
            interruption,
            cast(bool, case["resume"]),
            _run,
        )
    ) == case["outcome"]
