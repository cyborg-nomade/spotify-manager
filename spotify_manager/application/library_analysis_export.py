"""Resumable export-resource preparation with original progress and staging order."""

from collections.abc import Callable

from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.domain.library_analysis_values import ResourceName


def prepare_export_resource[T: LibraryModel](
    session: AnalysisSession,
    resource: ResourceName,
    models: list[T],
    model_type: type[T],
    sort_key: Callable[[T], tuple[int, ...]],
) -> list[T]:
    """Deduplicate original export values and stage before accepting completion.

    Args:
        session: Original independent export analysis invocation.
        resource: Original active resource identity.
        models: Original complete export models.
        model_type: Original tolerant staging parser.
        sort_key: Original output ordering rule.

    Returns:
        Original complete prepared or resumed resource models.
    """
    state = session.checkpoint["resources"][resource]
    if state["status"] == "complete":
        completed = session.files.models(session.paths.stage(resource), model_type)
        if session.progress:
            session.progress(resource, len(completed), len(completed), "Complete")
        return completed
    total = len(models)
    session.notify(resource, 0, total, "Reading YourLibrary.json")
    by_id = _read_export(session, resource, models, total)
    prepared = sorted(by_id.values(), key=sort_key)
    session.files.publish(session.paths.stage(resource), prepared)
    state["status"] = "complete"
    state["total"] = len(prepared)
    state["skipped"] = total - len(prepared)
    session.save()
    session.event(
        "resource_completed",
        resource=resource,
        count=len(prepared),
        skipped=total - len(prepared),
    )
    session.notify(resource, total, total, "Complete")
    return prepared


def _read_export[T: LibraryModel](
    session: AnalysisSession, resource: ResourceName, models: list[T], total: int
) -> dict[str, T]:
    by_id: dict[str, T] = {}
    update_every = max(1, total // 100)
    for index, model in enumerate(models, start=1):
        if index == 1 or index % update_every == 0:
            session.check_cancel()
        by_id[model.spotify_id] = model
        if session.progress and (index == total or index % update_every == 0):
            session.progress(resource, index, total, "Reading YourLibrary.json")
    return by_id
