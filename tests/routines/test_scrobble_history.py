import base64
import gzip
import json
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.routines import scrobble_history


class FakeLastFm:
    def __init__(self, tracks: tuple[LastFmRecentTrack, ...]) -> None:
        self.tracks = tracks
        self.calls: list[tuple[int, int, int]] = []

    def recent_tracks(
        self,
        *,
        from_timestamp: int,
        to_timestamp: int,
        limit: int = 200,
    ) -> tuple[LastFmRecentTrack, ...]:
        self.calls.append((from_timestamp, to_timestamp, limit))
        return self.tracks


def write_export(path: Path) -> bytes:
    payload = {
        "username": "man-et-arms",
        "scrobbles": [
            {
                "track": "Known Track",
                "artist": "Known Artist",
                "album": "Known Album",
                "albumId": "album-id",
                "date": 1_000,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.read_bytes()


def write_legacy_delta(path: Path) -> None:
    records = [
        {
            "track": "Known Track",
            "artist": "Known Artist",
            "album": "Known Album",
            "timestamp_ms": 1_000,
        },
        {
            "track": "Legacy Track",
            "artist": "Legacy Artist",
            "album": "Legacy Album",
            "timestamp_ms": 2_000,
        },
    ]
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_dry_run_merges_export_legacy_and_api_without_writing(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    original = write_export(export_path)
    legacy_path = tmp_path / "recent.jsonl"
    write_legacy_delta(legacy_path)
    backup_dir = tmp_path / "backups"
    log_path = tmp_path / "update.jsonl"
    lastfm = FakeLastFm(
        (
            LastFmRecentTrack("Legacy Artist", "Legacy Track", "Legacy Album", 2),
            LastFmRecentTrack("Live Artist", "Live Track", "Live Album", 3),
        )
    )

    summary = scrobble_history.refresh_scrobble_history(
        lastfm,
        expected_username="man-et-arms",
        export_path=export_path,
        legacy_delta_path=legacy_path,
        backup_dir=backup_dir,
        log_path=log_path,
        dry_run=True,
        now=datetime.fromtimestamp(10, UTC),
    )

    assert summary.export_scrobbles == 1
    assert summary.legacy_scrobbles_added == 1
    assert summary.live_scrobbles_added == 1
    assert summary.total_scrobbles == 3
    assert summary.persisted is False
    assert lastfm.calls == [(2, 10, 200)]
    assert export_path.read_bytes() == original
    assert not backup_dir.exists()
    assert not log_path.exists()


def test_real_refresh_backs_up_then_atomically_replaces_export(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    original = write_export(export_path)
    legacy_path = tmp_path / "recent.jsonl"
    write_legacy_delta(legacy_path)
    backup_dir = tmp_path / "backups"
    log_path = tmp_path / "update.jsonl"
    lastfm = FakeLastFm(
        (LastFmRecentTrack("Live Artist", "Live Track", "Live Album", 3),)
    )

    summary = scrobble_history.refresh_scrobble_history(
        lastfm,
        expected_username="man-et-arms",
        export_path=export_path,
        legacy_delta_path=legacy_path,
        backup_dir=backup_dir,
        log_path=log_path,
        now=datetime(2026, 8, 4, tzinfo=UTC),
    )

    assert summary.persisted is True
    assert summary.backup_path is not None
    assert gzip.decompress(summary.backup_path.read_bytes()) == original
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert [record["track"] for record in payload["scrobbles"]] == [
        "Known Track",
        "Legacy Track",
        "Live Track",
    ]
    assert payload["scrobbles"][0]["albumId"] == "album-id"
    audit = json.loads(log_path.read_text(encoding="utf-8"))
    assert audit["total_scrobbles"] == 3
    assert audit["persisted"] is True


def test_current_refresh_records_successful_check_time_without_rewrite(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "lastfm.json"
    original = write_export(export_path)
    backup_dir = tmp_path / "backups"
    log_path = tmp_path / "update.jsonl"
    checked_at = datetime(2026, 8, 5, 14, 30, tzinfo=UTC)
    progress: list[str] = []

    summary = scrobble_history.refresh_scrobble_history(
        FakeLastFm(
            (LastFmRecentTrack("Known Artist", "Known Track", "Known Album", 1),)
        ),
        expected_username="man-et-arms",
        export_path=export_path,
        legacy_delta_path=None,
        backup_dir=backup_dir,
        log_path=log_path,
        now=checked_at,
        progress_callback=progress.append,
    )

    assert summary.persisted is False
    assert summary.live_scrobbles_added == 0
    assert export_path.read_bytes() == original
    assert export_path.stat().st_mtime == pytest.approx(checked_at.timestamp())
    assert not backup_dir.exists()
    assert "History already current; recorded successful check time" in progress
    assert log_path.exists()


def test_refresh_recovers_inline_fallback_before_replacing_lfs_pointer(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(
        "version https://git-lfs.github.com/spec/v1\n",
        encoding="utf-8",
    )
    payload = {
        "username": "man-et-arms",
        "scrobbles": [
            {
                "track": "Fallback Track",
                "artist": "Fallback Artist",
                "album": "Fallback Album",
                "date": 1_000,
            }
        ],
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode()))
    split_at = len(encoded) // 2
    Path(f"{export_path}.gz.b64.part-aa").write_bytes(encoded[:split_at])
    Path(f"{export_path}.gz.b64.part-ab").write_bytes(encoded[split_at:])
    progress: list[str] = []

    summary = scrobble_history.refresh_scrobble_history(
        FakeLastFm((LastFmRecentTrack("Live Artist", "Live Track", "Live Album", 2),)),
        expected_username="man-et-arms",
        export_path=export_path,
        legacy_delta_path=None,
        backup_dir=tmp_path / "backups",
        log_path=tmp_path / "log.jsonl",
        now=datetime.fromtimestamp(10, UTC),
        progress_callback=progress.append,
    )

    assert summary.persisted is True
    assert summary.backup_path is not None
    backup = json.loads(gzip.decompress(summary.backup_path.read_bytes()))
    assert backup == payload
    updated = json.loads(export_path.read_text(encoding="utf-8"))
    assert [record["track"] for record in updated["scrobbles"]] == [
        "Fallback Track",
        "Live Track",
    ]
    assert "Recovered Last.fm history from compressed fallback parts" in progress


def test_refresh_preserves_duplicate_scrobbles_at_the_same_second(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "lastfm.json"
    payload = {
        "username": "man-et-arms",
        "scrobbles": [
            {
                "track": "Double Scrobble",
                "artist": "Known Artist",
                "album": "Known Album",
                "date": 1_000,
            },
            {
                "track": "Double Scrobble",
                "artist": "Known Artist",
                "album": "Known Album",
                "date": 1_000,
            },
        ],
    }
    export_path.write_text(json.dumps(payload), encoding="utf-8")
    lastfm = FakeLastFm(
        (
            LastFmRecentTrack(
                "Known Artist",
                "Double Scrobble",
                "Known Album",
                1,
            ),
            LastFmRecentTrack(
                "Known Artist",
                "Double Scrobble",
                "Known Album",
                1,
            ),
            LastFmRecentTrack("Live Artist", "Live Track", "Live Album", 2),
        )
    )

    summary = scrobble_history.refresh_scrobble_history(
        lastfm,
        expected_username="man-et-arms",
        export_path=export_path,
        legacy_delta_path=None,
        backup_dir=tmp_path / "backups",
        log_path=tmp_path / "log.jsonl",
        now=datetime.fromtimestamp(10, UTC),
    )

    assert summary.export_scrobbles == 2
    assert summary.live_scrobbles_added == 1
    updated = json.loads(export_path.read_text(encoding="utf-8"))
    assert [record["track"] for record in updated["scrobbles"]] == [
        "Double Scrobble",
        "Double Scrobble",
        "Live Track",
    ]


def test_refresh_rejects_an_export_for_a_different_user(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    write_export(export_path)
    lastfm = FakeLastFm(())

    with pytest.raises(scrobble_history.ScrobbleHistoryError, match="not somebody"):
        scrobble_history.refresh_scrobble_history(
            lastfm,
            expected_username="somebody",
            export_path=export_path,
            legacy_delta_path=None,
            backup_dir=tmp_path / "backups",
            log_path=tmp_path / "log.jsonl",
        )

    assert lastfm.calls == []


@pytest.mark.parametrize(
    "record",
    [
        "not-an-object",
        {"artist": "Artist", "track": "Track", "date": True},
        {"artist": "Artist", "track": "Track", "date": "bad"},
        {"artist": "", "track": "Track", "date": 1},
        {"artist": "Artist", "track": "", "date": 1},
        {"artist": "Artist", "track": "Track", "date": -1},
    ],
)
def test_export_record_validation_rejects_malformed_scrobbles(record: object) -> None:
    with pytest.raises(scrobble_history.ScrobbleHistoryError, match="Scrobble 3"):
        scrobble_history._parse_export_record(record, 3)


def test_export_and_legacy_delta_reject_invalid_shapes(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(json.dumps({"scrobbles": "bad"}))
    with pytest.raises(scrobble_history.ScrobbleHistoryError, match="scrobbles"):
        scrobble_history._load_export(export_path)

    legacy_path = tmp_path / "legacy.jsonl"
    legacy_path.write_text("\n[]\n")
    with pytest.raises(scrobble_history.ScrobbleHistoryError, match="delta is invalid"):
        scrobble_history._load_legacy_delta(legacy_path)


def test_missing_or_invalid_export_is_reported(tmp_path: Path) -> None:
    with pytest.raises(scrobble_history.ScrobbleHistoryError):
        scrobble_history._load_export(tmp_path / "missing.json")


def test_refresh_rejects_empty_history(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(json.dumps({"username": "user", "scrobbles": []}))

    with pytest.raises(scrobble_history.ScrobbleHistoryError, match="history is empty"):
        scrobble_history.refresh_scrobble_history(
            FakeLastFm(()),
            expected_username="user",
            export_path=export_path,
            legacy_delta_path=None,
            backup_dir=tmp_path / "backups",
            log_path=tmp_path / "log.jsonl",
        )


def test_backup_write_log_and_timestamp_failures_are_wrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_path = tmp_path / "lastfm.json"
    write_export(export_path)
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    checked_at = datetime(2026, 8, 5, tzinfo=UTC)

    with pytest.raises(
        scrobble_history.ScrobbleHistoryError,
        match="Could not back up",
    ):
        scrobble_history._backup_export(
            export_path,
            blocked / "backups",
            checked_at,
        )

    with pytest.raises(scrobble_history.ScrobbleHistoryError, match="audit log"):
        scrobble_history._append_log(
            scrobble_history.ScrobbleHistorySummary(
                checked_at=checked_at,
                username="user",
                history=(),
                export_scrobbles=0,
                legacy_scrobbles_added=0,
                live_scrobbles_added=0,
                dry_run=False,
                persisted=False,
                backup_path=None,
            ),
            blocked / "log.jsonl",
        )

    with pytest.raises(scrobble_history.ScrobbleHistoryError, match="check time"):
        scrobble_history._mark_export_checked(tmp_path / "missing.json", checked_at)

    monkeypatch.setattr(
        scrobble_history.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(
        scrobble_history.ScrobbleHistoryError,
        match="atomically update",
    ):
        scrobble_history._write_export_atomic(
            export_path,
            {"username": "user"},
            [
                {
                    "artist": "Artist",
                    "track": "Track",
                    "album": "",
                    "date": 1,
                }
            ],
        )
    assert not list(tmp_path.glob(".lastfm.json.*.tmp"))
