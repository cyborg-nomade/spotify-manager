"""Export an ordered playlist proposal with its pinned evidence and coverage."""

import csv
import re
from io import StringIO

from fastapi import Response

from spotify_manager.domain.listening_playlist import PlaylistPreview
from spotify_manager.domain.listening_time import utc_iso
from spotify_manager.domain.listening_values import ListeningQuery


_FORMULA = re.compile(r"^\s*[=+\-@\t\r]")


def _safe_text(value: str) -> str:
    return "'" + value if _FORMULA.match(value) else value


def _metadata(
    snapshot: str, query: ListeningQuery, preview: PlaylistPreview
) -> tuple[tuple[str, str | int | None], ...]:
    totals = preview.summary
    return (
        ("Source snapshot", snapshot),
        ("Liked tracks snapshot", preview.library_snapshot),
        ("Liked tracks published", preview.source.published_at),
        ("Liked tracks SHA-256", preview.source.sha256),
        ("From", query.start.isoformat()),
        ("Through", query.end.isoformat()),
        ("Timezone", query.timezone),
        ("Artist filter", query.artist or "All artists"),
        ("Weekday filter (Monday=0)", query.weekday),
        ("Hour filter", query.hour),
        ("Order", "First selected recorded play, then original source row"),
        ("Selected plays", totals.selected_plays),
        ("Playlist tracks", totals.playlist_tracks),
        ("Repeat plays", totals.duplicate_plays),
        ("Unresolved plays", totals.unresolved_plays),
    )


def playlist_csv(
    snapshot: str, query: ListeningQuery, preview: PlaylistPreview
) -> Response:
    """Download all proposed URIs in their original first-play order.

    Args:
        snapshot: Pinned source history version.
        query: Shared filters used to create the proposal.
        preview: Complete proposal and its pinned liked-track evidence.

    Returns:
        A private UTF-8 CSV attachment with formula-safe published names.
    """
    output = StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerows(_metadata(snapshot, query, preview))
    writer.writerow(())
    writer.writerow(
        (
            "Position",
            "Spotify URI",
            "Published title",
            "Published artist credit",
            "First match evidence",
            "First selected UTC",
            "Selected plays",
            "Repeat plays",
        )
    )
    for row in preview.tracks:
        writer.writerow(
            (
                row.position,
                row.track.uri,
                _safe_text(row.track.name),
                _safe_text(row.track.artist),
                row.evidence,
                utc_iso(row.history.first_ms),
                row.plays,
                row.plays - 1,
            )
        )
    filename = f"listening-playlist-{query.start}-{query.end}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
