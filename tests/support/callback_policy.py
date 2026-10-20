"""Document the narrow reasons executable hooks may cross a dependency boundary."""

from tests.support.callback_paths import CallbackUse


NOTIFICATIONS = frozenset(
    [
        "announce",
        "callback",
        "complete",
        "completion_notifier",
        "echo",
        "emit",
        "event_callback",
        "events",
        "moved",
        "present",
        "previous_spotify_event_callback",
        "progress",
        "progress_callback",
        "progress_reader",
        "spotify_event_setter",
    ]
)

OBSERVATIONS = frozenset(
    [
        "clock",
        "index_reader",
        "local_year",
        "monotonic",
        "now",
        "pause",
        "random",
        "random_index_reader",
        "random_timestamp_reader",
        "retry_wait",
        "sleep",
        "sleeper",
        "timestamp_reader",
        "today",
        "wait",
    ]
)

INTERACTIONS = frozenset(
    [
        "action",
        "action_reader",
        "album_choice_reader",
        "artist_choice_reader",
        "artist_reader",
        "ask_something_old_artist",
        "choice",
        "choice_reader",
        "choose",
        "choose_composer",
        "composer_playlist_reader",
        "consume",
        "endpoint",
        "endpoint_reader",
        "historical_artist_choice_reader",
        "order",
        "order_reader",
        "reader",
        "release",
        "release_choice",
        "release_choice_reader",
        "release_reader",
        "release_selector",
        "selector",
        "track",
        "track_choice",
        "track_choice_reader",
        "transition_reader",
    ]
)

CANCELLATION = frozenset(["cancel", "cancel_check", "cancelled", "check_cancel"])

RETRIES = frozenset(
    ["caller", "caller_retry", "configured_retry", "operation", "retry", "retry_call"]
)

BOUNDARY_HOOKS: dict[tuple[str, str], str] = {
    (
        "spotify_manager.bootstrap.library_lookups.cached_tracks",
        "factory",
    ): "Retained public cache-miss client factory.",
    (
        "spotify_manager.bootstrap.library_lookups.local_album",
        "factory",
    ): "Retained public cache-miss client factory.",
    (
        "spotify_manager.infrastructure.lookup_resources.AlbumTrackCache",
        "factory",
    ): "Retained public cache-miss client factory.",
    (
        "spotify_manager.processors.library_lookups.get_album_tracklist",
        "client_factory",
    ): "Retained public cache-miss client factory.",
    (
        "spotify_manager.processors.library_lookups.evaluate_album",
        "client_factory",
    ): "Retained public cache-miss client factory.",
    (
        "spotify_manager.core.state.compat.LegacyFileState.__init__",
        "loader",
    ): "Retained external Python state adapter.",
    (
        "spotify_manager.core.state.compat.LegacyFileState.__init__",
        "saver",
    ): "Retained external Python state adapter.",
    (
        "spotify_manager.core.state.compat.routine_state",
        "default_factory",
    ): "Retained external Python state adapter.",
    (
        "spotify_manager.core.state.compat.routine_state",
        "legacy_loader",
    ): "Retained external Python state adapter.",
    (
        "spotify_manager.core.state.compat.routine_state",
        "legacy_saver",
    ): "Retained external Python state adapter.",
    (
        "spotify_manager.core.state.definitions.CompatibilityDefinition",
        "factory",
    ): "Adapt external state hooks once to named schema methods.",
    (
        "spotify_manager.core.state.definitions.CompatibilityDefinition",
        "validator",
    ): "Adapt external state hooks once to named schema methods.",
    (
        "spotify_manager.core.state.definitions.state_definition",
        "source",
    ): "Normalize the retained Python service API at entry.",
    (
        "spotify_manager.core.state.definitions.state_definition",
        "validator",
    ): "Normalize the retained Python service API at entry.",
    (
        "spotify_manager.core.state.definitions.validate_definition",
        "source",
    ): "Normalize the retained Python manual-edit API at entry.",
    (
        "spotify_manager.core.state.service.StateService.namespace",
        "default_factory",
    ): "Retained Python namespace API; normal routines pass named schemas.",
    (
        "spotify_manager.core.state.service.StateService.namespace",
        "validator",
    ): "Retained Python namespace API; normal routines pass named schemas.",
    (
        "spotify_manager.core.state.service.StateService.replace_namespace",
        "validator",
    ): "Retained Python manual-edit API; HTTP passes named schemas.",
    (
        "spotify_manager.core.state.service.StateNamespace.__init__",
        "default_factory",
    ): "Retained Python namespace API; normalize immediately.",
    (
        "spotify_manager.core.state.service.StateNamespace.__init__",
        "validator",
    ): "Retained Python namespace API; normalize immediately.",
    (
        "spotify_manager.infrastructure.automation_http.SpaceHttpClient.__init__",
        "opener",
    ): "urllib transport protocol, never a business stage.",
    (
        "spotify_manager.infrastructure.library_analysis_catalog.SpotifyOffsetPages",
        "_method",
    ): "Private SDK endpoint handle captured at the original observation time.",
    (
        "spotify_manager.routines.genre_reveal.discover_genre_source",
        "page_reader",
    ): "Retained public page-reader hook; normalize to GenrePages at entry.",
    (
        "spotify_manager.routines.genre_reveal.load_genre_playlist_source",
        "page_reader",
    ): "Retained public page-reader hook; normalize to GenrePages at entry.",
    (
        "spotify_manager.routines.genre_reveal.process_next_genre",
        "page_reader",
    ): "Retained public page-reader hook; normalize to GenrePages at entry.",
    (
        "spotify_manager.interfaces.operations.genre_reveal.process_next_genre",
        "page_reader",
    ): "Normalize the retained public page-reader hook at entry.",
    (
        "spotify_manager.infrastructure.genre_pages.CompatibilityGenrePages",
        "reader",
    ): "Retained public page-reader hook; internal execution uses read().",
    (
        "spotify_manager.infrastructure.genre_pages.genre_pages",
        "reader",
    ): "Normalize the retained public page-reader hook at entry.",
    (
        "spotify_manager.routines.review_artists.flush_pending_queue_moves",
        "get_membership",
    ): "Retained public membership hook, adapted once to a reader object.",
    (
        "spotify_manager.interfaces.operations.review_artists.flush_pending_queue_moves",
        "get_membership",
    ): "Retained public membership hook, adapted once to a reader object.",
    (
        "spotify_manager.interfaces.operations.review_artists._CompatibilityMembership",
        "read",
    ): "Retained public membership hook; internal execution uses get().",
    (
        "spotify_manager.routines.analyse_library.prepare_export_resource",
        "sort_key",
    ): "Retained public sorting hook; application selects its fixed key directly.",
    (
        "spotify_manager.application.artist_review_effects.ReviewInteraction",
        "track",
    ): "Operator selection, never a replaceable business decision.",
    (
        "spotify_manager.application.artist_review_effects.ReviewInteraction",
        "release",
    ): "Operator selection, never a replaceable business decision.",
    (
        "spotify_manager.application.job_lifecycle.await_submission",
        "consume",
    ): "Observe the next submitted operator choice.",
    (
        "spotify_manager.application.album_recommendations.choose_album",
        "choice_reader",
    ): "Operator selection supplied by the interface.",
    (
        "spotify_manager.application.discography_planning.DiscographyReads",
        "choose",
    ): "Operator selection supplied by the interface.",
    (
        "spotify_manager.application.sauvignon_selection.AlbumEditionChoice",
        "reader",
    ): "Operator selection supplied by the interface.",
    (
        "spotify_manager.interfaces.cli.features.discography.DiscographyCLI",
        "ask_something_old_artist",
    ): "Operator selection supplied by the interface.",
    (
        "spotify_manager.application.credited_artists.CreditedArtistDependencies",
        "announce",
    ): "Notify the interface of an accepted effect; no business decision.",
    (
        "spotify_manager.application.wine_cellar.CellarWorkflow",
        "moved",
    ): "Notify the interface of an accepted effect; no business decision.",
    (
        "spotify_manager.application.wine_cellar.refill_cellar",
        "moved",
    ): "Notify the interface of an accepted effect; no business decision.",
    (
        "spotify_manager.application.wine_cellar.CellarRefill",
        "moved",
    ): "Notify the interface of an accepted effect; no business decision.",
    (
        "spotify_manager.core.state.compat.routine_state",
        "validator",
    ): "Retained external Python state adapter.",
}


def callback_reason(use: CallbackUse) -> str | None:
    """Explain why a callback is an actual hook or a retained outer Python API.

    Args:
        use: Parsed callback dependency declaration.

    Returns:
        Documented reason, or none for prohibited execution indirection.
    """
    compatibility = BOUNDARY_HOOKS.get((use.owner, use.parameter))
    if compatibility:
        return compatibility
    if _notification(use):
        return "Operator progress, completion or SDK event notification."
    if use.parameter in OBSERVATIONS:
        return "Time, randomness or bounded waiting observation."
    if use.parameter in CANCELLATION:
        return "Cancellation requested outside the business decision."
    if _retry_hook(use):
        return "Retry policy or the operation explicitly being retried."
    if _operator_choice(use):
        return "Operator selection supplied by the interface."
    return None


def _operator_choice(use: CallbackUse) -> bool:
    if use.parameter not in INTERACTIONS:
        return False
    for token in (
        "Choice",
        "ActionReader",
        "Selector",
        "ReleaseOrder",
        "TrackAction",
        "Transition",
        "Composer",
        "Completion",
    ):
        if token in use.annotation:
            return True
    return False


def _notification(use: CallbackUse) -> bool:
    if use.parameter not in NOTIFICATIONS:
        return False
    for token in (
        "Echo",
        "Progress",
        "Event",
        "MessageSink",
        "Completion",
        "Callable[[str]",
        "Callable[[int",
    ):
        if token in use.annotation:
            return True
    return False


def _retry_hook(use: CallbackUse) -> bool:
    if use.parameter != "operation":
        return use.parameter in RETRIES and (
            "Retry" in use.annotation or "Callable[[Callable" in use.annotation
        )
    name = use.owner.rsplit(".", 1)[-1]
    if "retry" in name or "Retry" in use.owner:
        return True
    return name in {
        "call",
        "direct_call",
        "_direct",
        "_direct_call",
        "_immediate",
        "call_direct",
        "spotify_call",
    }
