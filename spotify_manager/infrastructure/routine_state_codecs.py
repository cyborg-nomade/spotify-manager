"""Named formats for the retained routine state files and shared namespaces."""

from pathlib import Path
from typing import Any


class DiscographyStateCodec:
    """Own the original discography state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.discography import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.discography import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.discography import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.discography import save_state

        save_state(value, path)


class GenreRevealStateCodec:
    """Own the original genre reveal state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.genre_reveal import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.genre_reveal import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.genre_reveal import _load_state_dict

        return _load_state_dict(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.genre_reveal import _save_state_dict

        _save_state_dict(value, path)


class NewKidsStateCodec:
    """Own the original new kids state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.new_kids import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.new_kids import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.new_kids import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.new_kids import save_state

        save_state(value, path)


class NewWineStateCodec:
    """Own the original new wine state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.new_wine import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.new_wine import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.new_wine import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.new_wine import save_state

        save_state(value, path)


class PalaceOfMemoryStateCodec:
    """Own the original palace of memory state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.palace_of_memory import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.palace_of_memory import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.palace_of_memory import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.palace_of_memory import save_state

        save_state(value, path)


class Queue3StateCodec:
    """Own the original queue 3 state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.queue_3 import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.queue_3 import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.queue_3 import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.queue_3 import save_state

        save_state(value, path)


class RecoverRemovedAlbumsStateCodec:
    """Own the original recover removed albums state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.recover_removed_albums import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.recover_removed_albums import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.recover_removed_albums import _load_log_state

        return _load_log_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.recover_removed_albums import _save_log_state

        _save_log_state(value, path)


class ReleaseCheckStateCodec:
    """Own the original release check state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.release_check import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.release_check import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.release_check import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.release_check import save_state

        save_state(value, path)


class ReviewAlbumLimitsStateCodec:
    """Own the original review album limits state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        return dict()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.review_album_limits import (
            validate_review_decisions,
        )

        return validate_review_decisions(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.review_album_limits import load_review_decisions

        return load_review_decisions(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.review_album_limits import save_review_decisions

        save_review_decisions(value, path)


class ReviewArtistsStateCodec:
    """Own the original review artists state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.review_artists import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.review_artists import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.review_artists import _load_log_state

        return _load_log_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.review_artists import _save_log_state

        _save_log_state(value, path)


class SlowListeningStateCodec:
    """Own the original slow listening state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.slow_listening import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.slow_listening import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.slow_listening import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.slow_listening import save_state

        save_state(value, path)


class TheQueueStateCodec:
    """Own the original the queue state format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh missing-namespace value.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.the_queue import _default_state

        return _default_state()

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate the original namespace format.

        Args:
            raw: Original raw.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.the_queue import validate_state

        return validate_state(raw)

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Original path.

        Returns:
            Original normalized JSON value.
        """
        from spotify_manager.routines.the_queue import load_state

        return load_state(path)

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept complete legacy state.

        Args:
            value: Original value.
            path: Original path.
        """
        from spotify_manager.routines.the_queue import save_state

        save_state(value, path)


class NewYearStateDefinition:
    """Own the annual retrospective namespace format."""

    def default(self) -> dict[str, Any]:
        """Construct a fresh annual namespace.

        Returns:
            Original empty year mapping.
        """
        return {"years": {}}

    def validate(self, raw: object) -> dict[str, Any]:
        """Validate annual checkpoint values.

        Args:
            raw: Untrusted namespace.

        Returns:
            Original normalized state.
        """
        from spotify_manager.routines.new_year import validate_state

        return validate_state(raw)
