"""Validate persisted cover evidence before publishing a complete cache generation."""

import re
from datetime import datetime

from pydantic import TypeAdapter

from spotify_manager.domain.listening_cover_values import AlbumCoverMetadata
from spotify_manager.domain.listening_cover_values import CoverImage
from spotify_manager.domain.listening_cover_values import LastFmArtwork
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.infrastructure.listening.cover_image import cover_artwork
from spotify_manager.infrastructure.listening.cover_image import lastfm_album_page
from spotify_manager.infrastructure.listening.cover_image import lastfm_artwork
from spotify_manager.infrastructure.listening.cover_image import validate_cover_image
from spotify_manager.infrastructure.listening.cover_search import cover_mbid


METADATA = TypeAdapter(AlbumCoverMetadata)
MAX_DOCUMENT_BYTES = 32768


def _candidate_evidence(metadata: AlbumCoverMetadata) -> None:
    candidates, count = metadata.candidates, metadata.candidate_count
    if not 0 <= count <= 100 or len(candidates) != min(count, 5):
        raise ValueError("Cached album candidate counts disagree.")
    if len({item.mbid for item in candidates}) != len(candidates):
        raise ValueError("Cached album candidates are not distinct.")
    for candidate in candidates:
        cover_mbid(candidate.mbid)
        if (
            listening_identity((candidate.artist, candidate.title))
            != metadata.album_key
        ):
            raise ValueError("Cached album names are not corroborated.")
        if (
            max(len(candidate.title), len(candidate.artist), len(candidate.description))
            > 1000
        ):
            raise ValueError("Cached album candidate text exceeded its limit.")


def _coherent(metadata: AlbumCoverMetadata) -> bool:
    state, count = metadata.state, metadata.candidate_count
    if (state == "ready") != (metadata.artwork is not None):
        return False
    if isinstance(metadata.artwork, LastFmArtwork):
        page = lastfm_album_page(metadata.artist_name, metadata.album_name)
        return count == 0 and metadata.artwork.page_url == page
    if state in {"ready", "no_cover"}:
        return count == 1
    if state == "unmatched":
        return count == 0
    if state == "ambiguous":
        return count > 1
    return state == "incomplete"


def decode_cover_metadata(document: str) -> AlbumCoverMetadata:
    """Decode strict persisted fields and verify name, time and outcome coherence.

    Args:
        document: Complete credential-free serialized cover observation.

    Returns:
        Validated current metadata, independent of historical album IDs.

    Raises:
        ValueError: Malformed fields, counts, names, dates or outcomes.
        CoverSourceError: A cached provider identity is malformed.
    """
    if len(document.encode()) > MAX_DOCUMENT_BYTES:
        raise ValueError("Cached album document exceeded its limit.")
    metadata = METADATA.validate_json(document, strict=True)
    names = metadata.artist_name, metadata.album_name
    if any(not item.strip() or len(item) > 1000 for item in names):
        raise ValueError("Cached album names are invalid.")
    if listening_identity(names) != metadata.album_key or not _coherent(metadata):
        raise ValueError("Cached album identity or outcome disagrees.")
    if datetime.fromisoformat(metadata.fetched_at).utcoffset() is None:
        raise ValueError("Cached album time needs a timezone.")
    _candidate_evidence(metadata)
    return metadata


def decode_cover_image(
    metadata: AlbumCoverMetadata, content: bytes | None
) -> CoverImage | None:
    """Bind validated bytes to the exact artwork metadata before publication.

    Args:
        metadata: Validated observation.
        content: Stored JPEG bytes, or no image.

    Returns:
        Immutable image when required by the observation.

    Raises:
        ValueError: Bytes and metadata do not describe the same image.
        CoverSourceError: The image or source identity is invalid.
    """
    art = metadata.artwork
    if art is None:
        if content is not None:
            raise ValueError("Cached image has no supporting artwork evidence.")
        return None
    if isinstance(art, LastFmArtwork):
        if content is None:
            raise ValueError("Cached Last.fm artwork is missing.")
        expected, thumbnail = lastfm_artwork(content, art.page_url)
        if expected != art:
            raise ValueError("Cached Last.fm artwork bytes and evidence disagree.")
        return thumbnail
    cover_mbid(art.release_mbid)
    if not re.fullmatch(r"[0-9]{1,30}", art.image_id) or content is None:
        raise ValueError("Cached artwork identity or bytes are invalid.")
    image = validate_cover_image(content)
    if cover_artwork(image, art.release_mbid, art.image_id) != art:
        raise ValueError("Cached artwork bytes and evidence disagree.")
    return image
