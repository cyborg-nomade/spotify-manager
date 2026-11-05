"""New-record classification uses selected record identity and continuation intent."""

import pytest

from spotify_manager.domain.new_wine import starts_new_record
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))


@pytest.mark.parametrize(
    "plan,expected",
    [
        ({"action": "advance", "release": {"spotify_id": "album"}}, False),
        ({"action": "advance", "release": {"spotify_id": "other"}}, True),
        ({"action": "drop", "continuation_target": {"spotify_id": "next"}}, True),
        ({"action": "sauvignon", "continuation_target": {"spotify_id": "next"}}, True),
        ({"action": "sauvignon", "release": {"spotify_id": "other"}}, False),
        ({"action": "drop"}, False),
        ({"action": "advance", "release": None}, False),
        ({"action": "advance", "continuation_target": None}, False),
    ],
)
def test_only_new_record_markers_are_deferred(
    plan: dict[str, object], expected: bool
) -> None:
    """Do not defer ordinary next tracks or completions without a new marker.

    Args:
        plan: Accepted plan fields relevant to record classification.
        expected: Whether its New Wine append starts another record.
    """
    assert starts_new_record(SOURCE, plan) is expected
