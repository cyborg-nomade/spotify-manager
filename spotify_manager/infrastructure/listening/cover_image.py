"""Validate small JPEG thumbnails before they enter the protected image cache."""

import hashlib
from io import BytesIO

from PIL import Image
from PIL import UnidentifiedImageError

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.domain.listening_cover_values import CoverArtwork
from spotify_manager.domain.listening_cover_values import CoverImage
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
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise CoverSourceError("Cover image exceeded its size limit.")
    try:
        with Image.open(BytesIO(content), formats=("JPEG",)) as image:
            _check_dimensions(image)
            image.load()
    except OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError:
        raise CoverSourceError("Cover image was not a supported thumbnail.") from None
    return CoverImage(hashlib.sha256(content).hexdigest(), content)


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
