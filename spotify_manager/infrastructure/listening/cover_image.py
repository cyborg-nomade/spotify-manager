"""Validate small JPEG thumbnails before they enter the protected image cache."""

import hashlib
from io import BytesIO
from urllib.parse import quote

from PIL import Image
from PIL import UnidentifiedImageError

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.domain.listening_cover_values import CoverArtwork
from spotify_manager.domain.listening_cover_values import CoverImage
from spotify_manager.domain.listening_cover_values import LastFmArtwork
from spotify_manager.infrastructure.listening.cover_http import MAX_IMAGE_BYTES


def validate_cover_image(content: bytes) -> CoverImage:
    """Require a bounded, decodable JPEG thumbnail with safe pixel dimensions.

    Args:
        content: Complete bytes read from the fixed public thumbnail endpoint.

    Returns:
        Immutable validated bytes under their SHA-256 identity.

    Raises:
        CoverSourceError: Invalid format, dimensions, encoding or byte size.
    """
    _decode_dimensions(content, ("JPEG",))
    return CoverImage(hashlib.sha256(content).hexdigest(), content)


def _decode_dimensions(content: bytes, formats: tuple[str, ...]) -> tuple[int, int]:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise CoverSourceError("Cover image exceeded its size limit.")
    try:
        with Image.open(BytesIO(content), formats=formats) as image:
            _check_dimensions(image)
            image.load()
            return image.size
    except OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError:
        raise CoverSourceError("Cover image was not a supported thumbnail.") from None


def lastfm_album_page(artist: str, title: str) -> str:
    """Build the public Last.fm catalogue link from the corroborated credit and title.

    Args:
        artist: Exact album artist credit.
        title: Exact album title.

    Returns:
        A fixed-host Last.fm catalogue URL.
    """
    return (
        "https://www.last.fm/music/"
        + quote(artist, safe="")
        + "/"
        + quote(title, safe="")
    )


def lastfm_artwork(content: bytes, page: str) -> tuple[LastFmArtwork, CoverImage]:
    """Validate intact JPEG or PNG artwork and bind it to its attribution.

    Args:
        content: Bounded original image bytes.
        page: Derived Last.fm catalogue link.

    Returns:
        Validated artwork attribution and original thumbnail.
    """
    width, height = _decode_dimensions(content, ("JPEG", "PNG"))
    digest = hashlib.sha256(content).hexdigest()
    return LastFmArtwork("lastfm", page, digest, width, height), CoverImage(
        digest, content
    )


def cover_artwork(image: CoverImage, release: str, image_id: str) -> CoverArtwork:
    """Record dimensions and the representative release/image provenance.

    Args:
        image: Already validated immutable thumbnail.
        release: Validated source release MBID.
        image_id: Validated archive image identifier.

    Returns:
        Exact representative artwork metadata, without claiming edition identity.
    """
    with Image.open(BytesIO(image.content), formats=("JPEG",)) as decoded:
        return CoverArtwork(
            release, image_id, image.sha256, decoded.width, decoded.height
        )


def _check_dimensions(image: Image.Image) -> None:
    if not 1 <= image.width <= 1000 or not 1 <= image.height <= 1000:
        raise ValueError("Invalid thumbnail dimensions.")
