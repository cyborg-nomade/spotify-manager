"""Preserve optional history progress when no review observer is installed."""

from unittest.mock import Mock

from spotify_manager.application.ports.runtime import ReviewProgressMessages


def test_history_message_without_an_observer_is_a_noop() -> None:
    """Keep optional history output usable before an interactive review exists."""
    ReviewProgressMessages(None).echo("Reading history")


def test_history_message_keeps_the_original_zero_count_notification() -> None:
    """Forward the complete message without inventing review progress."""
    observer = Mock()
    ReviewProgressMessages(observer).echo("Reading history")
    observer.progress.assert_called_once_with(0, 0, "Reading history")
