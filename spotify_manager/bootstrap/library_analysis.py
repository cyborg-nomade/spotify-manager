"""Bind original file seams and synchronous Spotify reads for library analysis."""

import asyncio

from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_publication import AnalysisPublication
from spotify_manager.application.library_analysis_values import CancelCheck
from spotify_manager.application.library_analysis_values import Checkpoint
from spotify_manager.application.library_analysis_values import Echo
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import ProgressCallback
from spotify_manager.application.library_analysis_values import Sleep
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.library_analysis_values import RetryWait
from spotify_manager.infrastructure.analysis_async_files import AsyncAnalysisStorage
from spotify_manager.infrastructure.library_analysis_catalog import (
    SpotifyAnalysisCatalog,
)
from spotify_manager.infrastructure.library_analysis_publication import AnalysisBackups
from spotify_manager.infrastructure.library_analysis_retry import LibraryRetry
from spotify_manager.infrastructure.output import STANDARD_OUTPUT


def analysis_files() -> AsyncAnalysisStorage:
    """Bind original public file, audit and clock compatibility seams.

    Returns:
        Invocation dependencies preserving caller substitutions.
    """
    return AsyncAnalysisStorage()


def analysis_publication() -> AnalysisPublication:
    """Bind original undo, recovery and history-period compatibility seams.

    Returns:
        Complete ordered publication boundaries for an analysis invocation.
    """
    return AnalysisBackups(analysis_files().source)


def analysis_session(
    paths: LibraryAnalysisPaths,
    checkpoint: Checkpoint,
    spotify: Spotify | None = None,
    echo: Echo = STANDARD_OUTPUT,
    progress: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    sleep: Sleep = asyncio,
    retry_base_seconds: int = 10,
    retry_max_seconds: int = 1800,
) -> AnalysisSession:
    """Bind one original public invocation to independently injected stages.

    Args:
        paths: Original output family.
        checkpoint: Original mutable progress.
        spotify: Original caller-owned live client.
        echo: Original presenter.
        progress: Original resource-level progress.
        retry_wait: Original interactive retry decision.
        cancel_check: Original durable cancellation observation.
        sleep: Original blocking retry wait.
        retry_base_seconds: Original first transient delay.
        retry_max_seconds: Original maximum transient delay.

    Returns:
        Complete application session with no singleton resolution in inner code.
    """
    catalog = SpotifyAnalysisCatalog(spotify)
    retry = LibraryRetry(
        paths,
        checkpoint,
        analysis_files(),
        echo,
        retry_wait,
        sleep,
        retry_base_seconds,
        retry_max_seconds,
    )
    return AnalysisSession(
        paths,
        checkpoint,
        analysis_files(),
        catalog,
        retry,
        echo,
        progress,
        cancel_check,
    )
