"""Stable Sauvignon recommendation errors independent of clients and storage."""


class SauvignonError(RuntimeError):
    """Base error for the original Sauvignon recommendation workflow."""


class SauvignonConfigError(SauvignonError):
    """Original missing-setting or invalid numeric-request error."""


class SauvignonStateError(SauvignonError):
    """Original unreadable or unwritable durable recommendation-data error."""


class SauvignonSpotifyError(SauvignonError):
    """Original incomplete or unusable catalog or playlist observation error."""
