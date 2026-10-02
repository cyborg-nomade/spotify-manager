"""Yearly discovery playlist creation preserves validation and checkpoint boundaries."""

from dataclasses import dataclass

import pytest

from spotify_manager.application.discovery_destinations import GreatDiscoveries
from spotify_manager.application.new_kids_values import NewKidsError
from tests.support.discovery_effects import MemoryEffects


@dataclass
class MemoryCreation(MemoryEffects):
    """Observe profile/create/checkpoint/message order with injectable responses.

    Args:
        user_id: Observed current-profile identifier.
        created_id: Observed created-playlist identifier.
    """

    user_id: str = "user"
    created_id: str = "new-playlist"

    def current_user(self) -> str:
        """Observe the existing profile read.

        Returns:
            Configured parsed profile identifier.
        """
        self._record("profile", None)
        return self.user_id

    def create(self, user_id: str, year: int) -> str:
        """Observe private destination creation.

        Args:
            user_id: Accepted profile identifier.
            year: Original review year.

        Returns:
            Configured parsed created-playlist identifier.
        """
        self._record("create", (user_id, year))
        return self.created_id

    def preview_creation(self, year: int) -> None:
        """Observe creation preview without profile or checkpoint effects.

        Args:
            year: Original review year.
        """
        self._record("preview", year)

    def created(self, year: int) -> None:
        """Observe successful creation presentation after checkpoint.

        Args:
            year: Original review year.
        """
        self._record("created", year)


def _service(memory: MemoryCreation) -> GreatDiscoveries:
    return GreatDiscoveries(memory, memory, memory)


def _state() -> dict[str, object]:
    return {"great_discoveries_playlists": {}}


@pytest.mark.parametrize("preview", [False, True])
def test_stored_yearly_identifier_wins_without_observation(preview: bool) -> None:
    """An existing string destination overrides seed and preview creation logic."""
    memory = MemoryCreation()
    state: dict[str, object] = {"great_discoveries_playlists": {"2026": " "}}
    assert _service(memory).resolve(state, 2026, "seed", preview) == " "
    assert memory.events == []


@pytest.mark.parametrize("preview", [False, True])
def test_2026_seed_is_checkpointed_only_during_real_execution(preview: bool) -> None:
    """The configured seed never requires a profile or playlist creation call."""
    memory = MemoryCreation()
    state = _state()
    assert _service(memory).resolve(state, 2026, "seed", preview) == "seed"
    assert state["great_discoveries_playlists"] == ({} if preview else {"2026": "seed"})
    assert [name for name, value in memory.events] == (
        [] if preview else ["checkpoint"]
    )


def test_future_year_preview_omits_remote_creation_and_state_mutation() -> None:
    """Creation previews retain the original message-only behavior."""
    memory = MemoryCreation()
    state = _state()
    assert _service(memory).resolve(state, 2030, "seed", True) is None
    assert state == _state()
    assert memory.events == [("preview", 2030)]


@pytest.mark.parametrize("stored", [None, 12, ""])
def test_creation_replaces_invalid_saved_identifier_then_checkpoints(
    stored: object,
) -> None:
    """Only a nonempty string suppresses new playlist creation."""
    memory = MemoryCreation()
    state: dict[str, object] = {"great_discoveries_playlists": {"2030": stored}}
    assert _service(memory).resolve(state, 2030, "seed", False) == "new-playlist"
    assert [name for name, value in memory.events] == [
        "profile",
        "create",
        "checkpoint",
        "created",
    ]
    assert memory.events[1] == ("create", ("user", 2030))
    assert state["great_discoveries_playlists"] == {"2030": "new-playlist"}


@pytest.mark.parametrize("field", ["user_id", "created_id"])
def test_invalid_remote_identifier_stops_before_checkpoint(field: str) -> None:
    """Profile and creation response validation retain their original error messages."""
    memory = MemoryCreation()
    setattr(memory, field, "")
    state = _state()
    message = (
        "invalid current-user profile" if field == "user_id" else "created playlist id"
    )
    with pytest.raises(NewKidsError, match=message):
        _service(memory).resolve(state, 2030, "seed", False)
    assert "checkpoint" not in [name for name, value in memory.events]
    assert state == _state()


@pytest.mark.parametrize("boundary", ["profile", "create", "checkpoint", "created"])
def test_creation_failures_stop_at_the_original_boundary(boundary: str) -> None:
    """Checkpoint failure preserves the accepted identifier in the working state."""
    memory = MemoryCreation(fail_at=boundary)
    state = _state()
    expected = ["profile", "create", "checkpoint", "created"]
    with pytest.raises(OSError, match=boundary):
        _service(memory).resolve(state, 2030, "seed", False)
    assert [name for name, value in memory.events] == expected[
        : expected.index(boundary) + 1
    ]
    expected_state = (
        {"2030": "new-playlist"} if boundary in {"checkpoint", "created"} else {}
    )
    assert state["great_discoveries_playlists"] == expected_state


def test_missing_or_invalid_playlist_container_retains_original_errors() -> None:
    """The resolver does not manufacture missing namespace containers."""
    memory = MemoryCreation()
    with pytest.raises(KeyError):
        _service(memory).resolve({}, 2026, "seed", False)
    with pytest.raises(AssertionError):
        _service(memory).resolve(
            {"great_discoveries_playlists": []}, 2026, "seed", False
        )
    assert memory.events == []
