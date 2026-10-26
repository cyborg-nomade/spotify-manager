"""Named public-page access and the retained external Python reader hook."""

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


PUBLIC_GENRE_PAGES = PublicGenrePages()
