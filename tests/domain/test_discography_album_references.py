"""Direct album parsing and exact-ID edition deduplication."""

import pytest

from spotify_manager.domain.discography_links import ReviewRelease
from spotify_manager.domain.discography_links import album_reference
from spotify_manager.domain.discography_links import merge_review_release
from spotify_manager.domain.discography_links import split_album_references
from spotify_manager.domain.discography_values import CatalogRelease


FIRST = "a" * 22
SECOND = "b" * 22


def _entry(identity: str, date: str) -> ReviewRelease:
    record = CatalogRelease(
        identity,
        f"spotify:album:{identity}",
        "Record",
        "Album",
        date,
        date,
        10,
        "record",
        False,
        True,
        0,
        False,
    )
    return ReviewRelease(record, ("Artist",), True)


@pytest.mark.parametrize(
    "reference",
    [
        FIRST,
        f" {FIRST}\n",
        f"spotify:album:{FIRST}",
        f"https://open.spotify.com/album/{FIRST}",
        f"https://open.spotify.com/album/{FIRST}/?si=tracking#fragment",
        f"https://open.spotify.com/intl-pt/album/{FIRST}?si=tracking",
    ],
)
def test_direct_album_references_preserve_exact_identity(reference: str) -> None:
    """Tracking and locale paths cannot change the selected edition.

    Args:
        reference: Supported direct reference form.
    """
    assert album_reference(reference) == FIRST


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "not an album",
        "a" * 21,
        "a" * 23,
        f"spotify:track:{FIRST}",
        f"https://open.spotify.com/track/{FIRST}",
        f"http://open.spotify.com/album/{FIRST}",
        f"https://example.com/album/{FIRST}",
        f"https://open.spotify.com.evil/album/{FIRST}",
        f"https://user@open.spotify.com/album/{FIRST}",
        f"https://open.spotify.com:443/album/{FIRST}",
        f"https://open.spotify.com/album/{FIRST}/extra",
        "https://[invalid",
    ],
)
def test_invalid_or_other_resource_references_fail_explicitly(reference: str) -> None:
    """Parsing never follows an arbitrary URL or silently guesses a different kind.

    Args:
        reference: Unsupported or malformed reference.
    """
    with pytest.raises(ValueError):
        album_reference(reference)


def test_exact_duplicate_reuses_option_without_collapsing_alternate_edition() -> None:
    """Same-title linked editions retain exact IDs, ordered by their own dates."""
    original = _entry(FIRST, "2001")
    alternate = _entry(SECOND, "2011")
    assert merge_review_release((original,), original) == (original,)
    assert merge_review_release((alternate,), original) == (original, alternate)


def test_pasted_reference_batches_keep_order_and_drop_separators() -> None:
    """CLI and textareas accept conventional whitespace and comma-separated lists."""
    assert split_album_references(f" {FIRST},\nspotify:album:{SECOND}; ") == (
        FIRST,
        f"spotify:album:{SECOND}",
    )
    assert split_album_references(" \n ") == ()
