"""Public recommendation errors independent of external clients and storage."""


class FoundArtError(RuntimeError):
    """Base error for the Found Art recommendation routine."""


class FoundArtConfigError(FoundArtError):
    """Raised when required Last.fm or Spotify settings are missing."""


class FoundArtStateError(FoundArtError):
    """Raised when a cache, delta, or audit file cannot be used safely."""
