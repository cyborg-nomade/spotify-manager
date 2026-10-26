"""Named source and publication resources for library export uploads."""

from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import HfApi

from spotify_manager.application.upload_values import GeneratedPart
from spotify_manager.application.upload_values import LibraryFilesUploadPlan
from spotify_manager.infrastructure.upload_hub import UploadFailure
from spotify_manager.infrastructure.upload_hub import manifest


class ExportPreparation:
    """Read and encode exports using the retained format implementations."""

    def read(self, path: Path, key: str) -> tuple[bytes, int]:
        """Read and shallowly validate selected bytes.

        Args:
            path: Export location.
            key: Required top-level array.

        Returns:
            Original bytes and row count.
        """
        from spotify_manager.routines.upload_library_files import (
            _load_and_validate_export,
        )

        return _load_and_validate_export(path, expected_list_key=key)

    def parts(self, path: Path, content: bytes) -> tuple[GeneratedPart, ...]:
        """Encode deterministic history fallbacks without materializing files.

        Args:
            path: Original history location.
            content: Accepted export bytes.

        Returns:
            Deterministic generated parts.
        """
        from spotify_manager.routines.upload_library_files import _build_lastfm_parts

        return _build_lastfm_parts(path, content)


@dataclass(frozen=True)
class HubUpload:
    """Own one caller-selected Hub client and its upload artifact operations.

    Args:
        client: Selected synchronous Hub client.
    """

    client: HfApi

    def remote(self, plan: LibraryFilesUploadPlan) -> list[str]:
        """Read complete remote file names.

        Args:
            plan: Target repository and revision.

        Returns:
            Remote file names.
        """
        from spotify_manager.bootstrap.upload_library import _remote

        return _remote(self.client, plan)

    def materialize(self, plan: LibraryFilesUploadPlan) -> None:
        """Accept local fallbacks and remove obsolete local parts.

        Args:
            plan: Accepted upload plan.
        """
        from spotify_manager.routines.upload_library_files import (
            materialize_lastfm_parts,
        )

        materialize_lastfm_parts(plan)

    def manifest(self, plan: LibraryFilesUploadPlan, stale: set[str]) -> list[object]:
        """Encode ordered SDK operations.

        Args:
            plan: Accepted upload plan.
            stale: Obsolete remote fallbacks.

        Returns:
            Ordered operations.
        """
        return manifest(plan, stale)

    def commit(self, plan: LibraryFilesUploadPlan, operations: list[object]) -> object:
        """Accept one remote commit.

        Args:
            plan: Target revision and source order.
            operations: Ordered SDK operations.

        Returns:
            Commit metadata.
        """
        from spotify_manager.bootstrap.upload_library import _commit

        return _commit(self.client, plan, operations)

    def failure(self, stage: str, repo: str) -> UploadFailure:
        """Open the original transport error translation scope.

        Args:
            stage: Listing or commit boundary.
            repo: Target repository.

        Returns:
            Error translation context.
        """
        return UploadFailure(stage, repo)
