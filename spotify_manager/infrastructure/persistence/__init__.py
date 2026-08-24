"""Local persistence adapters."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from spotify_manager.infrastructure.persistence.json_library_data_store import (
        JsonLibraryDataStore,
    )
    from spotify_manager.infrastructure.persistence.json_state_store import (
        JsonStateStore,
    )


__all__ = ["JsonLibraryDataStore", "JsonStateStore"]


def __getattr__(name: str) -> object:
    """Load adapters lazily so core ports remain independent."""
    if name == "JsonLibraryDataStore":
        from spotify_manager.infrastructure.persistence.json_library_data_store import (
            JsonLibraryDataStore,
        )

        return JsonLibraryDataStore
    if name == "JsonStateStore":
        from spotify_manager.infrastructure.persistence.json_state_store import (
            JsonStateStore,
        )

        return JsonStateStore
    raise AttributeError(name)
