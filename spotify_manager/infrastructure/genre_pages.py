"""Named public-page access and the retained external Python reader hook."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class GenrePages(Protocol):
    """Read Every Noise and Spotify embed pages."""

    def read(self, url: str) -> str:
        """Read complete public HTML.

        Args:
            url: Original public source URL.

        Returns:
            Complete decoded page.
        """
        ...


class PublicGenrePages:
    """Read public pages through the original HTTP implementation."""

    def read(self, url: str) -> str:
        """Read complete public HTML.

        Args:
            url: Original source URL.

        Returns:
            Complete decoded page.
        """
        from spotify_manager.routines.genre_reveal import read_public_page

        return read_public_page(url)


@dataclass(frozen=True)
class CompatibilityGenrePages:
    """Adapt an external Python page hook once at the compatibility edge.

    Args:
        reader: Existing caller-supplied public-page hook.
    """

    reader: Callable[[str], str]

    def read(self, url: str) -> str:
        """Observe the external caller's page source.

        Args:
            url: Original source URL.

        Returns:
            Complete decoded page.
        """
        return self.reader(url)


def genre_pages(reader: Callable[[str], str]) -> GenrePages:
    """Normalize the retained external Python hook at the interface edge.

    Args:
        reader: Existing public source hook or the original default reader.

    Returns:
        Named page access used throughout internal discovery.
    """
    from spotify_manager.routines.genre_reveal import read_public_page

    if reader is read_public_page:
        return PublicGenrePages()
    return CompatibilityGenrePages(reader)
