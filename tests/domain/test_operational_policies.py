"""Exercise pure original deployment, maintenance and upload manifest decisions."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from spotify_manager.domain import automation_calendar as calendar
from spotify_manager.domain import web_access as access
from spotify_manager.domain.upload_manifest import LibraryFilesUploadError
from spotify_manager.domain.upload_manifest import part_suffix
from spotify_manager.domain.upload_manifest import stale_parts


@dataclass
class AccessObservations:
    """Observe exact credential and delayed-peer decision boundaries.

    Args:
        local: Original direct-peer qualification.
        peers: Number of peer observations.
        comparisons: Original ordered constant-time comparison inputs.
    """

    local: bool
    peers: int = 0
    comparisons: list[tuple[str, str]] = field(default_factory=list)

    def peer(self) -> bool:
        """Observe the original peer lazily.

        Returns:
            Original local-peer qualification.
        """
        self.peers += 1
        return self.local

    def compare(self, supplied: str, expected: str) -> bool:
        """Record original credential comparison precedence.

        Args:
            supplied: Original header.
            expected: Original configured credential.

        Returns:
            Original credential equality.
        """
        self.comparisons.append((supplied, expected))
        return supplied == expected


@pytest.mark.parametrize("password", [None, "", "secret"])
@pytest.mark.parametrize("method", ["GET", "OPTIONS", "POST"])
@pytest.mark.parametrize("path", ["/health", "/", "/protected", "/health/"])
def test_open_gate_precedes_credentials(
    password: str | None, method: str, path: str
) -> None:
    """Retain original disabled, preflight and exact-path bypasses.

    Args:
        password: Original configured value.
        method: Original request method.
        path: Original exact URL path.
    """
    assert access.is_open(password, method, path) == (
        password is None or method == "OPTIONS" or path in access.OPEN_PATHS
    )


@pytest.mark.parametrize("supplied", ["", "secret", "wrong"])
@pytest.mark.parametrize("automation", ["", "token", "wrong"])
@pytest.mark.parametrize("configured", [None, "", "token"])
@pytest.mark.parametrize("allow", [False, True])
@pytest.mark.parametrize("local", [False, True])
def test_credentials_retain_lazy_peer_and_comparison_order(
    supplied: str, automation: str, configured: str | None, allow: bool, local: bool
) -> None:
    """Protect original automation precedence, local bypass and final comparison.

    Args:
        supplied: Original password header.
        automation: Original automation header.
        configured: Original automation configuration.
        allow: Original local-development flag.
        local: Original direct-peer qualification.
    """
    observations = AccessObservations(local)
    accepted_automation = bool(automation and configured and automation == configured)
    expected = (
        accepted_automation
        or bool(supplied and allow and local)
        or supplied == "secret"
    )
    result = access.credential_matches(
        supplied,
        "secret",
        automation,
        configured,
        allow,
        observations.peer,
        observations.compare,
    )
    assert result is expected
    assert observations.peers == int(
        not accepted_automation and bool(supplied) and allow
    )
    comparisons = []
    if automation and configured:
        comparisons.append((automation, configured))
    if not accepted_automation and not (supplied and allow and local):
        comparisons.append((supplied, "secret"))
    assert observations.comparisons == comparisons


@pytest.mark.parametrize(
    "index,suffix", [(0, "aa"), (25, "az"), (26, "ba"), (675, "zz")]
)
def test_original_upload_suffix(index: int, suffix: str) -> None:
    """Retain original two-letter identities.

    Args:
        index: Original part position.
        suffix: Original encoded name.
    """
    assert part_suffix(index) == suffix


@pytest.mark.parametrize("index", [-1, 676])
def test_upload_suffix_limits(index: int) -> None:
    """Retain original overflow rejection.

    Args:
        index: Original unrepresentable position.
    """
    with pytest.raises(LibraryFilesUploadError, match="too many"):
        part_suffix(index)


def test_stale_manifest_requires_generated_parts() -> None:
    """Remove only old fallback families when generated parts are selected."""
    remote = {"file.gz", "file.gz.part-aa", "file.b64-aa", "file.b64-zz", "other"}
    assert stale_parts(remote, set(), "file.gz", "file.gz.part-", "file.b64-") == set()
    assert stale_parts(
        remote, {"file.b64-aa"}, "file.gz", "file.gz.part-", "file.b64-"
    ) == {"file.gz", "file.gz.part-aa", "file.b64-zz"}


@pytest.mark.parametrize(
    "instant,deadline,opened,start",
    [
        (
            "2026-01-15T22:30:00+00:00",
            "2026-01-16T04:00:00+00:00",
            True,
            "2026-01-15T21:00:00+00:00",
        ),
        (
            "2026-07-15T22:30:00+00:00",
            "2026-07-16T03:00:00+00:00",
            True,
            "2026-07-15T20:00:00+00:00",
        ),
        (
            "2026-07-16T00:00:00+00:00",
            "2026-07-16T03:00:00+00:00",
            True,
            "2026-07-15T20:00:00+00:00",
        ),
        (
            "2026-07-15T10:00:00+00:00",
            "2026-07-15T15:00:00+00:00",
            False,
            "2026-07-15T20:00:00+00:00",
        ),
        (
            "2026-10-24T22:00:00+00:00",
            "2026-10-25T04:00:00+00:00",
            True,
            "2026-10-24T20:00:00+00:00",
        ),
        (
            "2026-03-28T22:00:00+00:00",
            "2026-03-29T03:00:00+00:00",
            True,
            "2026-03-28T21:00:00+00:00",
        ),
    ],
)
def test_original_maintenance_calendar(
    instant: str, deadline: str, opened: bool, start: str
) -> None:
    """Retain UTC boundaries through both Berlin DST transitions.

    Args:
        instant: Original observation time.
        deadline: Original maintenance end.
        opened: Original schedule qualification.
        start: Original maintenance opening.
    """
    now = datetime.fromisoformat(instant)
    timezone = ZoneInfo("Europe/Berlin")
    assert calendar.maintenance_deadline(now, timezone) == datetime.fromisoformat(
        deadline
    )
    assert calendar.scheduled_window_is_open(now, timezone) is opened
    assert calendar.maintenance_window_start(now, timezone) == datetime.fromisoformat(
        start
    )


@pytest.mark.parametrize(
    "instant,expected",
    [
        ("2026-12-31T23:00:00+00:00", True),
        ("2026-12-31T22:59:59+00:00", False),
        ("2026-10-04T00:30:00+02:00", True),
        ("2026-10-11T00:30:00+02:00", False),
        ("2026-11-01T00:30:00+01:00", True),
        ("2026-11-07T00:30:00+01:00", False),
    ],
)
def test_original_rebuild_dates(instant: str, expected: bool) -> None:
    """Retain New Year and first-Sunday qualification in local time.

    Args:
        instant: Original observation time.
        expected: Original history rebuild selection.
    """
    assert (
        calendar.scrobble_rebuild_due(
            datetime.fromisoformat(instant), ZoneInfo("Europe/Berlin")
        )
        is expected
    )


def test_artifact_freshness_requires_all_inclusive_observations() -> None:
    """Retain all-file completeness and inclusive timestamps."""
    now = datetime(2026, 9, 24, tzinfo=UTC)
    required = frozenset({"one", "two"})
    assert not calendar.artifacts_are_fresh({"one": now}, required, now)
    assert calendar.artifacts_are_fresh({"one": now, "two": now}, required, now)
    assert not calendar.artifacts_are_fresh(
        {"one": datetime(2026, 9, 23, tzinfo=UTC), "two": now}, required, now
    )
