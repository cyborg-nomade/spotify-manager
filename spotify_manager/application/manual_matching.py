"""Invocation-owned operator interactions for track and album resolution."""

from typing import Protocol

from spotify_manager.application.manual_album_matching import AlbumMatchInteraction
from spotify_manager.application.manual_track_matching import TrackMatchInteraction
from spotify_manager.application.ports.runtime import Cancellation


class CatalogMatchInteraction(
    TrackMatchInteraction, AlbumMatchInteraction, Cancellation, Protocol
):
    """Own catalog choices and the same invocation's cancellation boundary."""
