"""Original Queue configuration, state and integration errors."""


class QueueError(RuntimeError):
    """Base error for The Queue routines."""


class QueueConfigError(QueueError):
    """Raised when a required playlist or recommendation setting is absent."""


class QueueStateError(QueueError):
    """Raised when Queue state, cache, or audit data is malformed."""


class QueueSpotifyError(QueueError):
    """Raised when Spotify returns an incomplete response."""
