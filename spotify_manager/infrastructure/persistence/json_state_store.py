"""Atomic local implementation of the central state store."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock

from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.models import new_document
from spotify_manager.core.state.models import validate_document


MISSING_REVISION = "missing"


class JsonStateStore:
    """Persist the complete state document in one atomic JSON file."""

    def __init__(self, path: Path) -> None:
        """Use one local path as the complete state document."""
        self.path = path
        self._lock = Lock()

    @staticmethod
    def _revision(contents: bytes) -> str:
        return hashlib.sha256(contents).hexdigest()

    def _read_unlocked(self) -> StateSnapshot:
        if not self.path.exists():
            return StateSnapshot(new_document(), MISSING_REVISION)
        try:
            contents = self.path.read_bytes()
            raw = json.loads(contents)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateDocumentError(f"Could not read state from {self.path}.") from exc
        return StateSnapshot(validate_document(raw), self._revision(contents))

    def read(self) -> StateSnapshot:
        """Read one validated local snapshot."""
        with self._lock:
            return self._read_unlocked()

    def write(
        self,
        document: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> StateSnapshot:
        """Atomically replace the file when its content hash still matches."""
        del message
        validated = validate_document(document)
        contents = (
            json.dumps(validated, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode()
        with self._lock:
            current = self._read_unlocked()
            if current.revision != expected_revision:
                raise StateConflictError(
                    "Shared state changed before the local write completed."
                )
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(contents)
                temporary.replace(self.path)
            except OSError as exc:
                raise StateDocumentError(
                    f"Could not write state to {self.path}."
                ) from exc
        return StateSnapshot(validated, self._revision(contents))
