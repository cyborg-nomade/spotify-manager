"""Apply one Requeue transition through explicit, synchronous dependencies."""

from dataclasses import dataclass

from spotify_manager.application.ports.listening import AuditWriter
from spotify_manager.application.ports.listening import Clock
from spotify_manager.application.ports.listening import MessageSink
from spotify_manager.application.ports.requeue import RequeueCatalog
from spotify_manager.application.ports.requeue import RequeuePlaylists
from spotify_manager.application.requeue_result import RequeueForADreamChangedError
from spotify_manager.application.requeue_result import RequeueForADreamSummary
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography import release_transition
from spotify_manager.domain.requeue import RequeuePlan
from spotify_manager.domain.requeue import plan_transition


@dataclass(frozen=True)
class RequeueDependencies:
    """Dependencies owned by the invoking CLI or HTTP operation.

    Args:
        playlists: Fresh reads and ordered individual playlist effects.
        catalog: Studio discography and track access.
        echo: Existing mutation messages, delivered after each accepted effect.
        progress: Optional progress callback, retaining cancellation boundaries.
        audit: Existing completion writer, called after the result timestamp.
        clock: Timestamp source, read only when constructing the final result.
    """

    playlists: RequeuePlaylists
    catalog: RequeueCatalog
    echo: MessageSink
    progress: MessageSink | None
    audit: AuditWriter[RequeueForADreamSummary]
    clock: Clock


def _progress(dependencies: RequeueDependencies, message: str) -> None:
    if dependencies.progress is not None:
        dependencies.progress(message)


def _plan(
    dependencies: RequeueDependencies, playlist: tuple[PlaylistTrack, ...]
) -> RequeuePlan:
    if not playlist:
        return plan_transition(playlist, None, None, ())
    source = playlist[0]
    _progress(dependencies, f"Loading {source.primary_artist_name}'s discography")
    discography = dependencies.catalog.discography(source.primary_artist_id)
    current, following = release_transition(source.release.name, discography)
    if following is None:
        return plan_transition(playlist, current, None, ())
    _progress(dependencies, f"Loading {following.name}")
    tracks = dependencies.catalog.release_tracks(following)
    return plan_transition(playlist, current, following, tracks)


def _recheck(
    dependencies: RequeueDependencies, playlist_id: str, source: PlaylistTrack
) -> None:
    _progress(dependencies, "Rechecking the playlist head")
    current = dependencies.playlists.sources(playlist_id)
    if not current or current[0].spotify_id != source.spotify_id:
        raise RequeueForADreamChangedError(
            "Requeue for a Dream changed before the update; nothing was changed."
        )


def _replace_marker(
    dependencies: RequeueDependencies, playlist_id: str, plan: RequeuePlan
) -> None:
    assert plan.source is not None
    target = plan.target
    if target is not None and not plan.already_present:
        dependencies.playlists.append(playlist_id, target)
        release_name = (
            plan.target_release.name if plan.target_release else "unknown release"
        )
        dependencies.echo(f"Added {target.name} ({release_name}).")
    elif target is not None:
        dependencies.echo(f"{target.name} is already present; it was not duplicated.")
    dependencies.playlists.remove(playlist_id, plan.source)
    dependencies.echo(f"Removed {plan.source.name} ({plan.source.release.name}).")


def _summary(
    dependencies: RequeueDependencies,
    playlist_id: str,
    dry_run: bool,
    plan: RequeuePlan,
) -> RequeueForADreamSummary:
    source, target, release = plan.source, plan.target, plan.target_release
    return RequeueForADreamSummary(
        recorded_at=dependencies.clock(),
        playlist_id=playlist_id,
        dry_run=dry_run,
        action=plan.action,
        playlist_length_before=plan.before,
        playlist_length_after=plan.after,
        artist=source.primary_artist_name if source else None,
        source_track=source.name if source else None,
        source_release=source.release.name if source else None,
        target_track=target.name if target else None,
        target_release=release.name if release else None,
        target_release_type=release.release_type if release else None,
        target_release_date=release.chronology_date if release else None,
        target_already_present=plan.already_present,
        reason=plan.reason,
    )


def flush_requeue(
    dependencies: RequeueDependencies, playlist_id: str, *, dry_run: bool = False
) -> RequeueForADreamSummary:
    """Advance one marker while retaining every read, write, and audit boundary.

    Args:
        dependencies: Explicit integrations, callbacks, audit writer, and clock.
        playlist_id: Already-parsed playlist identifier.
        dry_run: Preview without the final recheck, mutations, or audit.

    Returns:
        The original summary shape for empty, skip, drop, or advance outcomes.

    Raises:
        RequeueForADreamChangedError: The source head changed before mutation.
        RequeueForADreamError: A catalog, playlist, or audit operation fails.
        RuntimeError: Caller cancellation or retry policy interrupts execution.
    """
    _progress(dependencies, "Loading Requeue for a Dream")
    playlist = dependencies.playlists.sources(playlist_id)
    plan = _plan(dependencies, playlist)
    if not dry_run and plan.action in {"advance", "drop"}:
        assert plan.source is not None
        _recheck(dependencies, playlist_id, plan.source)
        _replace_marker(dependencies, playlist_id, plan)
    summary = _summary(dependencies, playlist_id, dry_run, plan)
    if not dry_run and plan.action != "empty":
        dependencies.audit(summary)
    return summary
