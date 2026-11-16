"""Typed HTTP envelopes carrying effective filters and one source version."""

from pydantic import BaseModel

from spotify_manager.application.listening_ports import ListeningReads
from spotify_manager.domain.listening_values import ListeningQuery


class ListeningEnvelope[T](BaseModel):
    """Pair analytical data with the exact source generation and applied filters."""

    snapshot: str
    filters: ListeningQuery
    data: T


def present_listening[T](
    index: ListeningReads, query: ListeningQuery, result: T
) -> ListeningEnvelope[T]:
    """Present a named use-case result without reading or changing application state.

    Args:
        index: Ready generation pinned by the HTTP boundary.
        query: Effective validated selection.
        result: Typed application result.

    Returns:
        Version-consistent HTTP representation.
    """
    return ListeningEnvelope(
        snapshot=index.metadata.snapshot, filters=query, data=result
    )
