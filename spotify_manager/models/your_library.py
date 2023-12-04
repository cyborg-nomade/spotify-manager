"""Your Library file models."""

from pydantic import BaseModel


class YourLibraryTrack(BaseModel):
    """Your Library tracks model."""

    artist: str
    album: str
    track: str
    uri: str

    @property
    def spotify_id(self) -> str:
        """."""
        return self.uri.split("spotify:track:")[-1]


class YourLibraryAlbum(BaseModel):
    """Your Library albums model."""

    artist: str
    album: str
    uri: str

    @property
    def spotify_id(self) -> str:
        """."""
        return self.uri.split("spotify:album:")[-1]


class YourLibraryArtist(BaseModel):
    """Your Library artists model."""

    name: str
    uri: str

    @property
    def spotify_id(self) -> str:
        """."""
        return self.uri.split("spotify:artist:")[-1]


class YourLibraryFile(BaseModel):
    """Your Library File model."""

    tracks: list[YourLibraryTrack]
    albums: list[YourLibraryAlbum]
    artists: list[YourLibraryArtist]
