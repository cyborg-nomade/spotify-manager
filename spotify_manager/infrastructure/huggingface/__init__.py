"""Hugging Face infrastructure adapters."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from spotify_manager.infrastructure.huggingface.library_data_store import (
        HubLibraryDataStore,
    )
    from spotify_manager.infrastructure.huggingface.state_store import HubStateStore


__all__ = ["HubLibraryDataStore", "HubStateStore"]


def __getattr__(name: str) -> object:
    """Load adapters lazily so their core ports cannot form import cycles."""
    if name == "HubLibraryDataStore":
        from spotify_manager.infrastructure.huggingface.library_data_store import (
            HubLibraryDataStore,
        )

        return HubLibraryDataStore
    if name == "HubStateStore":
        from spotify_manager.infrastructure.huggingface.state_store import HubStateStore

        return HubStateStore
    raise AttributeError(name)
