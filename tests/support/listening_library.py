"""Publish synthetic current collections independently of listening history."""

import json

from spotify_manager.core.library_data.models import ArtifactName
from tests.support.listening import ListeningFixture


def publish_collection(
    fixture: ListeningFixture, name: ArtifactName, rows: object
) -> None:
    """Publish one deliberately controlled local collection through real storage.

    Args:
        fixture: Isolated source, durable store and managed paths.
        name: Artists, albums or tracks collection.
        rows: Synthetic rows, including deliberately malformed fixtures.
    """
    fixture.service.paths[name].write_text(json.dumps(rows))
    fixture.service.publish(name, source="collection-fixture")


def album(name: str = "Record", identity: int = 1) -> dict[str, str]:
    """Return a saved-album fixture with a valid distinct Spotify identity."""
    return {"artist": "Alpha", "album": name, "uri": f"spotify:album:{identity:022d}"}
