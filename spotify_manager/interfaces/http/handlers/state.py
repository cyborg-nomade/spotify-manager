"""Original state HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from fastapi.responses import Response

from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.service import StateFactory
from spotify_manager.core.state.service import StateService
from spotify_manager.core.state.service import StateValidator
from spotify_manager.interfaces.http.models.state import (
    SharedStateNamespaceReplaceRequest,
)
from spotify_manager.interfaces.http.models.state import SharedStateReplaceRequest
from spotify_manager.interfaces.http.models.state import SharedStateSnapshot
from spotify_manager.interfaces.http.models.state import SharedStateSummary


@dataclass(kw_only=True)
class StateHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        STATE_NAMESPACE_DEFINITIONS: Existing overridable feature dependency.
        canonical_json: Existing overridable feature dependency.
        datetime: Existing overridable feature dependency.
        get_state_service: Existing overridable feature dependency.
        namespace_value: Existing overridable feature dependency.
        state_editor_schema: Existing overridable feature dependency.
        validate_namespace_editor_change: Existing overridable feature dependency.
    """

    STATE_NAMESPACE_DEFINITIONS: dict[str, tuple[StateFactory, StateValidator]]
    canonical_json: Callable[..., str]
    datetime: type[datetime]
    get_state_service: Callable[..., StateService]
    namespace_value: Callable[..., dict[str, Any] | None]
    state_editor_schema: Callable[..., dict[str, Any]]
    validate_namespace_editor_change: Callable[..., None]

    def shared_state_summary(self) -> SharedStateSummary:
        """Return state freshness without transferring the complete document.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        try:
            snapshot = self.get_state_service().snapshot()
        except StateConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except StateError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        namespaces = snapshot.document["namespaces"]
        return SharedStateSummary(
            revision=snapshot.revision,
            updated_at=snapshot.document[("updated_at")],
            namespaces=self._namespace_timestamps(namespaces),
        )

    def shared_state(self) -> SharedStateSnapshot:
        """Return the complete shared application state and revision guard.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        try:
            snapshot = self.get_state_service().snapshot()
        except StateConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except StateError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return SharedStateSnapshot(
            revision=snapshot.revision, document=snapshot.document
        )

    def shared_state_editor_schema(self) -> dict[str, Any]:
        """Return backend-owned controls and constraints for manual state edits.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        schema = self.state_editor_schema()
        if set(schema["namespaces"]) != set(self.STATE_NAMESPACE_DEFINITIONS):
            raise HTTPException(
                status_code=500,
                detail=(
                    "State editor schema and namespace validators are out of sync."
                ),
            )
        return schema

    def replace_shared_state_namespace(
        self, namespace: str, request: SharedStateNamespaceReplaceRequest
    ) -> SharedStateSnapshot:
        """Validate and replace only one namespace at the viewed revision.

        Args:
            namespace: Original validated namespace value.
            request: Original validated request value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        definition = self.STATE_NAMESPACE_DEFINITIONS.get(namespace)
        if definition is None:
            raise HTTPException(status_code=404, detail="Unknown state namespace.")
        default_factory, validator = definition
        service = self.get_state_service()
        try:
            current_snapshot = service.snapshot()
            current = self.namespace_value(current_snapshot.document, namespace)
            self.validate_namespace_editor_change(
                namespace,
                current if current is not None else default_factory(),
                request.value,
            )
            snapshot = service.replace_namespace(
                namespace,
                request.value,
                expected_revision=request.expected_revision,
                validator=validator,
                message=(f"Edit {namespace} state from web app"),
            )
        except StateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StateDocumentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except StateConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SharedStateSnapshot(
            revision=snapshot.revision, document=snapshot.document
        )

    def replace_shared_state(
        self, request: SharedStateReplaceRequest
    ) -> SharedStateSnapshot:
        """Manually replace shared state only when the viewed revision is current.

        Args:
            request: Original validated request value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        try:
            snapshot = self.get_state_service().replace(
                request.document,
                expected_revision=request.expected_revision,
                message=("Edit Spotify Manager state from web app"),
            )
        except StateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StateDocumentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except StateConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SharedStateSnapshot(
            revision=snapshot.revision, document=snapshot.document
        )

    def export_shared_state(self) -> Response:
        """Download the current shared state as a JSON snapshot.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        try:
            snapshot = self.get_state_service().snapshot()
        except StateConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except StateError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        timestamp = self.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return Response(
            self.canonical_json(
                {("revision"): snapshot.revision, ("document"): snapshot.document}
            )
            + "\n",
            media_type=("application/json"),
            headers={
                ("Content-Disposition"): (
                    f'attachment; filename="spotify-manager-state-{timestamp}.json"'
                )
            },
        )

    def _namespace_timestamps(
        self, namespaces: dict[str, dict[str, object]]
    ) -> dict[str, str]:
        result = {}
        for name, envelope in namespaces.items():
            result[name] = str(envelope["updated_at"])
        return result
