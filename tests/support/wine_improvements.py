"""Independent ordered markers and explicit cellar choices for Item 9."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

from spotify_manager.application.ports.cellar_review import TransferChoice
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release
from tests.support.new_wine_memory import MemoryWine


def mixed_wine() -> MemoryWine:
    """Create A finishing, B advancing and C finishing with two new records.

    Returns:
        Independent live playlists, catalog and ordered operator decisions.
    """
    a = studio_release("a-old", "A old")
    b = studio_release("b-old", "B old")
    c = studio_release("c-old", "C old")
    a_new = playlist_track("a-first", studio_release("a-new", "A new")).release
    c_new = playlist_track("c-first", studio_release("c-new", "C new")).release
    sources = [
        playlist_track("a-end", a),
        playlist_track("b-start", b),
        playlist_track("c-end", c),
    ]
    tracks = {
        a.spotify_id: (release_track("a-end"),),
        b.spotify_id: (release_track("b-start"), release_track("b-next")),
        c.spotify_id: (release_track("c-end"),),
        a_new.spotify_id: (release_track("a-first"),),
        c_new.spotify_id: (release_track("c-first"),),
    }
    return MemoryWine(
        playlists={"new": sources, "sauvignon": []},
        release_tracks=tracks,
        candidates=(a_new, c_new),
        liked={"a-end", "b-start", "c-end"},
        choices=["a-new", "c-new"],
    )


def single_and_advance() -> MemoryWine:
    """Replace A by a single selecting another record before B's existing advance.

    Returns:
        A mixed run with one newly selected release and one continuation.
    """
    memory = mixed_wine()
    source = memory.playlists["new"][0]
    assert isinstance(source, PlaylistTrack)
    single = replace(source.release, release_type="Single")
    memory.playlists["new"] = [
        replace(source, release=single),
        memory.playlists["new"][1],
    ]
    memory.choices = ["a-new"]
    return memory


def marker_ids(tracks: list[PlaylistTrack | ReleaseTrack]) -> list[str]:
    """Read accepted marker order independently of summaries and audit rows.

    Args:
        tracks: Simulated live playlist values.

    Returns:
        Ordered track identities, retaining duplicates.
    """
    return [track.spotify_id for track in tracks]


@dataclass(frozen=True)
class PlaylistEdit:
    """Model an external edit while a later source is being reviewed.

    Args:
        memory: Independent remote playlists and progress observations.
        remove_source: Whether to remove A instead of appending an external tail.
    """

    memory: MemoryWine
    remove_source: bool

    def progress(self, completed: int, total: int, label: str) -> None:
        """Edit at C's review boundary, after B advanced and before deferred effects.

        Args:
            completed: Original reviewed-source counter.
            total: Snapshotted source count.
            label: Current source label.
        """
        self.memory.progress(completed, total, label)
        if not label.endswith("c-end") or completed != 2:
            return
        if self.remove_source:
            self.memory.playlists["new"].pop(0)
            return
        self.memory.playlists["new"].append(release_track("external-tail"))


@dataclass
class TransferReader:
    """Return explicit decisions and interrupt a chosen cancellation boundary.

    Args:
        choices: Ordered accept, skip or quit decisions.
        offered: Observed candidate identities and eligibility counts.
        checks: Cancellation observations so far.
        interrupt_at: One check to interrupt, if requested.
    """

    choices: list[TransferChoice] = field(default_factory=list)
    offered: list[tuple[str, int | None, int | None]] = field(default_factory=list)
    checks: int = 0
    interrupt_at: int | None = None

    async def choose_transfer(
        self, source: PlaylistTrack, liked: int | None, albums: int | None
    ) -> TransferChoice:
        """Record the offered marker and return the next required decision.

        Args:
            source: Eligible source marker.
            liked: Observed liked-track count.
            albums: Observed saved-album count.

        Returns:
            Scripted explicit operator response.
        """
        self.offered.append((source.spotify_id, liked, albums))
        return self.choices.pop(0)

    def check(self) -> None:
        """Interrupt the requested boundary without accepting a playlist write.

        Raises:
            RuntimeError: The scripted owning invocation has been cancelled.
        """
        self.checks += 1
        if self.checks == self.interrupt_at:
            raise RuntimeError("transfer cancelled")
