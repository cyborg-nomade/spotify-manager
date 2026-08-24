"""Central, versioned application state."""

from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.editor import namespace_editor_schema
from spotify_manager.core.state.editor import state_editor_schema
from spotify_manager.core.state.editor import validate_namespace_editor_change
from spotify_manager.core.state.models import STATE_SCHEMA_VERSION
from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.service import StateNamespace
from spotify_manager.core.state.service import StateService
from spotify_manager.core.state.store import StateStore


__all__ = [
    "STATE_SCHEMA_VERSION",
    "StateConfigurationError",
    "StateConflictError",
    "StateDocumentError",
    "StateError",
    "StateNamespace",
    "RoutineState",
    "namespace_editor_schema",
    "state_editor_schema",
    "validate_namespace_editor_change",
    "StateService",
    "StateSnapshot",
    "StateStore",
]
