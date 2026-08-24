"""CLI contracts for viewing, editing, and exporting shared state."""

import json
from pathlib import Path

from typer.testing import CliRunner

from spotify_manager import main


def test_state_commands_round_trip_guarded_snapshot(tmp_path: Path) -> None:
    """Exported state can be edited, applied, and viewed by namespace."""
    runner = CliRunner()
    snapshot_path = tmp_path / "state.json"

    exported = runner.invoke(main.app, ["state-export", str(snapshot_path)])
    exported_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    document = exported_payload["document"]
    document["namespaces"]["manual"] = {
        "updated_at": document["updated_at"],
        "value": {"cursor": 7},
    }
    snapshot_path.write_text(
        json.dumps(
            {"revision": exported_payload["revision"], "document": document},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    edited = runner.invoke(
        main.app,
        ["state-edit", str(snapshot_path), "--yes"],
    )
    shown = runner.invoke(
        main.app,
        ["state-show", "--namespace", "manual"],
    )

    assert exported.exit_code == 0
    assert edited.exit_code == 0
    assert shown.exit_code == 0
    assert '"cursor": 7' in shown.output


def test_state_edit_rejects_stale_snapshot(tmp_path: Path) -> None:
    """A stale exported file cannot silently replace newer shared state."""
    runner = CliRunner()
    stale_path = tmp_path / "stale.json"
    current_path = tmp_path / "current.json"
    assert runner.invoke(main.app, ["state-export", str(stale_path)]).exit_code == 0
    current = json.loads(stale_path.read_text(encoding="utf-8"))
    current["document"]["updated_at"] = "2099-01-01T00:00:00+00:00"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    assert (
        runner.invoke(
            main.app,
            ["state-edit", str(current_path), "--force", "--yes"],
        ).exit_code
        == 0
    )

    stale = runner.invoke(main.app, ["state-edit", str(stale_path), "--yes"])

    assert stale.exit_code == 1
    assert "snapshot is stale" in stale.output
