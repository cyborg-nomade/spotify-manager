"""Recorded invocation values covering the entire frozen SDK endpoint subset."""

from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class EndpointCase:
    """Describe data for an SDK/native differential contract invocation.

    Args:
        name: Frozen SDK endpoint method name.
        args: Original positional values.
        keywords: Original keyword values.
    """

    name: str
    args: tuple[object, ...] = ()
    keywords: dict[str, object] = field(default_factory=dict)


CASES = (
    EndpointCase("album", ("abc",)),
    EndpointCase("album", ("abc",), {"market": "DE"}),
    EndpointCase("album_tracks", ("abc",)),
    EndpointCase("album_tracks", ("abc",), {"limit": 1, "offset": 9, "market": "DE"}),
    EndpointCase("albums", (("abc", "def", "abc"),)),
    EndpointCase("albums", (("abc", "def", "abc"),), {"market": "DE"}),
    EndpointCase("artist", ("abc",)),
    EndpointCase("artist_albums", ("abc",)),
    EndpointCase(
        "artist_albums",
        ("abc",),
        {"include_groups": "album,single", "country": "DE", "limit": 50, "offset": 7},
    ),
    EndpointCase("artist_top_tracks", ("abc",)),
    EndpointCase("artist_top_tracks", ("abc",), {"country": "DE"}),
    EndpointCase("current_user", ()),
    EndpointCase("current_user_followed_artists", ()),
    EndpointCase("current_user_followed_artists", (), {"limit": 50, "after": "abc"}),
    EndpointCase("current_user_following_artists", ()),
    EndpointCase(
        "current_user_following_artists",
        (),
        {"ids": ["abc", "spotify:artist:def", "abc"]},
    ),
    EndpointCase("current_user_playlists", ()),
    EndpointCase("current_user_playlists", (), {"limit": 1, "offset": 4}),
    EndpointCase("current_user_saved_albums", ()),
    EndpointCase(
        "current_user_saved_albums", (), {"limit": 2, "offset": 7, "market": "DE"}
    ),
    EndpointCase("current_user_saved_albums_add", ()),
    EndpointCase(
        "current_user_saved_albums_add",
        (),
        {"albums": ["abc", "spotify:album:def", "abc"]},
    ),
    EndpointCase("current_user_saved_albums_contains", ()),
    EndpointCase(
        "current_user_saved_albums_contains",
        (),
        {"albums": ["abc", "spotify:album:def", "abc"]},
    ),
    EndpointCase("current_user_saved_albums_delete", ()),
    EndpointCase(
        "current_user_saved_albums_delete",
        (),
        {"albums": ["abc", "spotify:album:def", "abc"]},
    ),
    EndpointCase("current_user_saved_tracks", ()),
    EndpointCase(
        "current_user_saved_tracks", (), {"limit": 2, "offset": 4, "market": "DE"}
    ),
    EndpointCase("current_user_saved_tracks_add", ()),
    EndpointCase(
        "current_user_saved_tracks_add",
        (),
        {"tracks": ["abc", "spotify:track:def", "abc"]},
    ),
    EndpointCase("current_user_saved_tracks_contains", ()),
    EndpointCase(
        "current_user_saved_tracks_contains",
        (),
        {"tracks": ["abc", "spotify:track:def", "abc"]},
    ),
    EndpointCase(
        "next", ({"next": "https://api.spotify.com/v1/me/tracks?offset=20&limit=20"},)
    ),
    EndpointCase("playlist_add_items", ("abc", ("def", "ghi"))),
    EndpointCase("playlist_add_items", ("abc", ("def", "ghi")), {"position": 0}),
    EndpointCase("search", ("Björk & Bach",)),
    EndpointCase(
        "search",
        ("Björk & Bach",),
        {"limit": 50, "offset": 2, "type": "artist,album", "market": "from_token"},
    ),
    EndpointCase("track", ("abc",)),
    EndpointCase("track", ("abc",), {"market": "DE"}),
    EndpointCase("tracks", (("abc", "def", "abc"),)),
    EndpointCase("tracks", (("abc", "def", "abc"),), {"market": "DE"}),
    EndpointCase("user_follow_artists", ()),
    EndpointCase(
        "user_follow_artists", (), {"ids": ["abc", "spotify:artist:def", "abc"]}
    ),
    EndpointCase("user_playlist_create", ("owner", "Björk 🍷")),
    EndpointCase(
        "user_playlist_create",
        ("owner", "Björk 🍷"),
        {"public": False, "collaborative": True, "description": "Café 🍷"},
    ),
)
