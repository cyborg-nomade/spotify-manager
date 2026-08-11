"""Tests for the interactive discography CLI command."""

from types import SimpleNamespace

from typer.testing import CliRunner

from spotify_manager import main


def test_plan_discographies_dry_run_prints_fractional_days(monkeypatch) -> None:
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
        lambda: SimpleNamespace(
            discography_newfoundland_playlist="nf",
            discography_memory_lane_playlist="ml",
            discography_requeue_playlist="rq",
            the_queue_3_playlist="q3",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())

    def build(_spotify, playlist_ids, _selector, **kwargs):
        received["playlist_ids"] = playlist_ids
        received["queue_3_playlist_id"] = kwargs["queue_3_playlist_id"]
        received["retry"] = callable(kwargs["retry_call"])
        return plan

    monkeypatch.setattr(main.discography, "build_discography_plan", build)

    result = CliRunner().invoke(
        main.app,
        ["plan-discographies", "--dry-run"],
    )

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
