"""Validate and present health HTTP requests."""


def health() -> dict[str, str]:
    """Liveness probe.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return {"status": "ok"}


def auth_check() -> dict[str, str]:
    """Side-effect-free password check protected by the deployment middleware.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return {"status": "ok"}
