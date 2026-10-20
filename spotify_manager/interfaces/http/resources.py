"""Deferred environment resource contracts for HTTP workers."""

from typing import Protocol

from spotify_manager.settings import Settings


class JobConfigurationReader(Protocol):
    """Observe configuration when a worker reaches its original setup stage."""

    def load(self) -> Settings:
        """Observe current environment configuration.

        Returns:
            Original settings model.
        """
        ...
