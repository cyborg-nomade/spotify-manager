"""Allow only SDK method capture required by frozen binding-time behavior."""

from tests.support.callback_arguments import FunctionArgument
from tests.support.callback_paths import CallbackUse


SDK_METHODS: dict[tuple[str, str], str] = {
    (
        "spotify_manager.infrastructure.library_analysis_catalog.SpotifyOffsetPages",
        "_method",
    ): "Capture the selected SDK endpoint once at the original scan boundary.",
    (
        "spotify_manager.infrastructure.spotify.events.SpotifyEvents",
        "_setter",
    ): "Restore through the exact optional SDK method observed when subscribing.",
}


def callback_reason(use: CallbackUse) -> str | None:
    """Explain only a specifically retained SDK method binding.

    Args:
        use: Parsed function-shaped field or parameter.

    Returns:
        Exact binding-time reason, or none for prohibited callback injection.
    """
    return SDK_METHODS.get((use.owner, use.parameter))


SORT_PARTIALS = {
    ("spotify_manager.domain.queue_seeds._SeedSelection.group", "_popular_order"),
    ("spotify_manager.domain.queue_seeds._SeedSelection.fallback", "_fallback_order"),
    ("spotify_manager.domain.recommendation_seeds._group_pool", "_popular_key"),
    ("spotify_manager.domain.recommendation_seeds._rank_group", "_weekly_key"),
    ("spotify_manager.domain.release_check.rank_artists", "_artist_rank"),
    ("spotify_manager.domain.release_check.rank_artists", "_display_rank"),
}


def function_argument_reason(use: FunctionArgument) -> str | None:
    """Explain the external API requirement for a function-valued argument.

    Args:
        use: Parsed function argument at its original call site.

    Returns:
        Narrow library or framework requirement, or none for execution injection.
    """
    if use.parameter == "key" and use.callee in {"sorted", "min", "max"}:
        return "Python's ordering API requires a key function."
    if use.parameter == "key" and use.callee.endswith(".sort"):
        return "The list.sort key API requires a function."
    if use.callee == "partial" and (use.owner, use.function) in SORT_PARTIALS:
        return "Bind fixed ranking data for the immediately enclosing ordering key."
    if use.callee == "json.dumps" and use.parameter == "default":
        return "The JSON encoder requires a default function for date values."
    return _framework_argument_reason(use)


def _framework_argument_reason(use: FunctionArgument) -> str | None:
    if use.owner == "spotify_manager.api":
        return _api_argument_reason(use)
    http = "spotify_manager.interfaces.http."
    if not use.owner.startswith(http):
        return None
    if use.callee in {"Thread", "jobs.Thread"} and use.parameter == "target":
        return "threading.Thread requires a target function at the HTTP job boundary."
    if use.callee == "Depends" and use.parameter == "0":
        return "FastAPI Depends requires the provider function at route registration."
    return None


def _api_argument_reason(use: FunctionArgument) -> str | None:
    if use.callee == "FastAPI" and use.parameter == "lifespan":
        return "FastAPI requires the lifespan context-manager function at construction."
    if use.callee.startswith("app.exception_handler(") and use.parameter == "0":
        return "FastAPI's exception-handler decorator requires the handler function."
    return None
