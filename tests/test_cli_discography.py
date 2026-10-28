"""Tests for the interactive discography CLI command."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def test_plan_discographies_dry_run_prints_fractional_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan discographies dry run prints fractional days.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    releases = tuple(
        main.discography.CatalogRelease(
            spotify_id=f"release-{index}",
            uri=f"spotify:album:release-{index}",
            name=f"Release {index}",
            release_type="Album",
            release_date="2020-01-01",
            chronology_date="2020-01-01",
            total_tracks=10,
            identity=f"release-{index}",
            saved=False,
            plain=True,
            edition_rank=0,
            default=True,
        )
        for index in range(3)
    )
    selection = main.discography.ArtistSelection(
        spotify_id="artist",
        name="Artist",
        source_queue="newfoundland",
        releases=releases,
        markers=(),
    )
    plan = main.discography.DiscographyPlan(
        start_queue="newfoundland",
        next_queue="memory_lane",
        artists=(selection,),
        total_releases=3,
        open_slots=7,
    )
    received: dict[str, object] = {}
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                discography_newfoundland_playlist="nf",
                discography_memory_lane_playlist="ml",
                discography_requeue_playlist="rq",
                the_queue_3_playlist="q3",
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    scenario = PlanDiscographiesDryRunPrintsFractionalDaysScenario(
        plan=plan, received=received
    )
    monkeypatch.setattr(
        main.discography,
        "build_discography_plan",
        AsyncMock(side_effect=scenario.build),
    )
    result = CliRunner().invoke(main.app, ["plan-discographies", "--dry-run"])
    assert result.exit_code == 0
    assert received["playlist_ids"] == {
        "newfoundland": "nf",
        "memory_lane": "ml",
        "requeue": "rq",
    }
    assert received["queue_3_playlist_id"] == "q3"
    assert received["retry"] is True
    assert "Artist" in result.output
    assert "1.5" in result.output
    assert "Dry run" in result.output


@dataclass
class PlanDiscographiesDryRunPrintsFractionalDaysScenario:
    """Retain the original plan discographies dry run prints fractional days fixture.

    Args:
        plan: Original plan observation or resource.
        received: Original received observation or resource.
    """

    plan: main.discography.DiscographyPlan
    received: dict[str, object]

    def build(
        self, _spotify: Any, playlist_ids: Any, _selector: Any, **kwargs: Any
    ) -> main.discography.DiscographyPlan:
        """Execute the original build mock boundary.

        Args:
            _spotify: Original external mock argument.
            playlist_ids: Original external mock argument.
            _selector: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received["playlist_ids"] = playlist_ids
        self.received["queue_3_playlist_id"] = kwargs["queue_3_playlist_id"]
        self.received["retry"] = callable(
            getattr(kwargs["retry_call"], "attempts", None)
        )
        return self.plan
