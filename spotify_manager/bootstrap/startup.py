"""Original process startup integration independent of routine business rules."""


def hydrate_library_data() -> None:
    """Hydrate durable artifacts at the original API lifespan boundary.

    Runtime retains the original authority, retry and publication behavior.
    No client is acquired by constructing or importing an application use case.
    """
    from spotify_manager.core.library_data.runtime import hydrate_runtime_library_data

    hydrate_runtime_library_data()
