"""Provide synthetic state and playlist results for Genre Reveal browser checks."""

from datetime import UTC
from datetime import datetime

from fastapi import APIRouter
from fastapi import HTTPException

from spotify_manager.infrastructure.genre_models import GenreRevealRunRequest
from spotify_manager.infrastructure.genre_models import GenreRevealRunResult
from spotify_manager.infrastructure.genre_models import GenreRevealSourcePreview
from spotify_manager.infrastructure.genre_models import GenreRevealState
from spotify_manager.infrastructure.genre_models import GenreRevealStateUpdate
from tests.browser.cockpit import flush_status


router = APIRouter(prefix="/genre-reveal")


def _initial_progress() -> GenreRevealState:
    return GenreRevealState(
        completed=["kerkkoor"], updated_at=datetime(2024, 10, 31, tzinfo=UTC)
    )


_progress = _initial_progress()


def reset_genre() -> None:
    """Restore the sample completed prefix and filter setting."""
    global _progress
    _progress = _initial_progress()


@router.get("/state")
async def genre_progress() -> GenreRevealState:
    """Read the process-local sample route progress."""
    return _progress


async def _require_normal_mode() -> None:
    if (await flush_status()).active:
        raise HTTPException(409, "Flush Mode blocks new Genre Reveal actions.")


@router.put("/state")
async def save_genre_progress(update: GenreRevealStateUpdate) -> GenreRevealState:
    """Save the route progress to process memory.

    Args:
        update: Completed slugs and the hide-completed preference.

    Returns:
        Updated fixture progress with an accepted timestamp.
    """
    global _progress
    await _require_normal_mode()
    _progress = GenreRevealState(
        completed=update.completed,
        hide_done=update.hide_done,
        updated_at=datetime.now(UTC),
    )
    return _progress


@router.get("/source")
async def preview_genre(slug: str, name: str) -> GenreRevealSourcePreview:
    """Return harmless local placeholders for the two source links.

    Args:
        slug: Genre identity requested by the route.
        name: Display name of that genre.

    Returns:
        Source metadata for this sample genre.
    """
    await _require_normal_mode()
    return GenreRevealSourcePreview(
        slug=slug,
        name=name,
        every_noise_url="about:blank#sample-every-noise",
        source_playlist_id="sample-source",
        source_playlist_uri="spotify:playlist:sample-source",
        source_playlist_url="about:blank#sample-spotify",
    )


@router.post("/run-next")
async def run_genre(update: GenreRevealRunRequest) -> GenreRevealRunResult:
    """Complete one sample genre with a fixed set of synthetic markers.

    Args:
        update: The genre chosen in the frontend.

    Returns:
        Sample playlist result and completion time.

    Raises:
        HTTPException: Flush Mode blocks the run or the genre is complete.
    """
    source = await preview_genre(update.slug, update.name)
    if update.slug in _progress.completed:
        raise HTTPException(409, "Sample genre is already complete.")
    _progress.completed.append(update.slug)
    now = datetime.now(UTC)
    _progress.updated_at = now
    return GenreRevealRunResult(
        **source.model_dump(),
        destination_playlist_id="sample-destination",
        source_track_uris=["spotify:track:sample-one", "spotify:track:sample-two"],
        added_track_uris=["spotify:track:sample-one"],
        already_present_track_uris=["spotify:track:sample-two"],
        completed_at=now,
    )
