"""Verify typed Discography raw accounting, saved batching and source gathering."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.discography_catalog import DiscographyCatalog
from spotify_manager.application.discography_catalog import DiscographyPage
from spotify_manager.application.discography_queues import DiscographyQueues
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.discography_boundaries import marker
from tests.support.discography_run import release


@dataclass
class MemoryCatalog:
    """Supply complete typed pages with independent raw-row accounting.

    Args:
        pages: Original typed pages keyed by raw offset.
        reads: Original ordered offsets.
        saved_reads: Original ordered membership batches.
    """

    pages: dict[int, DiscographyPage]
    reads: list[int] = field(default_factory=list)
    saved_reads: list[list[str]] = field(default_factory=list)

    def page(self, offset: int) -> DiscographyPage:
        """Read typed facts at the original raw offset.

        Args:
            offset: Original count of all raw rows already visited.

        Returns:
            Original typed page facts.
        """
        self.reads.append(offset)
        return self.pages[offset]

    def saved(self, identities: list[str]) -> list[bool]:
        """Observe ordered original saved batches.

        Args:
            identities: Original newest-by-ID unique releases.

        Returns:
            Original exact-length membership facts.
        """
        self.saved_reads.append(identities)
        return [True for identity in identities]


def test_discography_catalog_offsets_count_skipped_rows_and_replace_duplicate_ids() -> (
    None
):
    """Retain raw offsets, latest facts and original first identity insertion order."""
    first = release("a")
    last = replace(first, name="Latest")
    edge = MemoryCatalog(
        {0: DiscographyPage((first,), 2, True), 2: DiscographyPage((last,), 1, False)}
    )
    assert DiscographyCatalog(edge.page, edge.saved).run() == (
        replace(last, saved=True),
    )
    assert edge.reads == [0, 2]
    assert edge.saved_reads == [["a"]]


def test_discography_catalog_reads_all_candidates_before_saved_batches() -> None:
    """Retain twenty-release membership batches and complete catalog order."""
    releases = tuple(release(f"id-{index}") for index in range(43))
    edge = MemoryCatalog({0: DiscographyPage(releases, 43, False)})
    result = DiscographyCatalog(edge.page, edge.saved).run()
    assert len(result) == 43
    assert [len(batch) for batch in edge.saved_reads] == [20, 20, 3]
    assert all(item.saved for item in result)


@pytest.mark.parametrize("has_next", [False, True])
def test_discography_empty_catalog_obeys_original_next_authority(
    has_next: bool,
) -> None:
    """Reject empty next pages while accepting an empty completed catalog.

    Args:
        has_next: Original next-page truthiness.
    """
    edge = MemoryCatalog({0: DiscographyPage((), 0, has_next)})
    owner = DiscographyCatalog(edge.page, edge.saved)
    if has_next:
        with pytest.raises(DiscographyError, match="empty artist release page"):
            owner.run()
        return
    assert owner.run() == ()
    assert edge.saved_reads == []


@dataclass
class MemoryQueues:
    """Supply original ordered typed primary marker facts.

    Args:
        reads: Original ordered playlist identities.
    """

    reads: list[str] = field(default_factory=list)

    def read(self, playlist: str) -> tuple[PlaylistTrack, ...]:
        """Read complete original marker facts.

        Args:
            playlist: Original configured source identity.

        Returns:
            Original first-spelling and duplicate-URI scenarios.
        """
        self.reads.append(playlist)
        return (
            marker("first", "a", "Alpha"),
            marker("second", "b", "Beta"),
            marker("first", "a", "Changed"),
        )


@pytest.mark.parametrize("extra", [None, "", "extra"])
def test_discography_reads_sources_before_optional_auxiliary_markers(
    extra: str | None,
) -> None:
    """Retain source order and treat only none as an absent auxiliary playlist.

    Args:
        extra: Original optional auxiliary source.
    """
    edge = MemoryQueues()
    queues, markers = DiscographyQueues(
        edge.read, {"newfoundland": "nf", "memory_lane": "ml", "requeue": "rq"}, extra
    ).run()
    expected = ["nf", "ml", "rq"]
    if extra is not None:
        expected.append(extra)
    assert edge.reads == expected
    assert tuple(item.name for item in queues["memory_lane"]) == ("Alpha", "Beta")
    assert markers["a"][0].uris == ("first",)
    assert len(markers["a"]) == len(expected)
