"""Provider failures shared by the explicit country and artwork lookup ports."""


class ListeningProviderError(RuntimeError):
    """Keep retry evidence separate from the safe user-facing failure message."""

    def __init__(
        self, message: str, *, temporary: bool = False, retry_after: float = 0
    ) -> None:
        """Attach bounded-request policy inputs to a safe error.

        Args:
            message: Public explanation without URLs, names or response bodies.
            temporary: Whether retrying the same read may succeed.
            retry_after: Provider-requested minimum delay in seconds.
        """
        super().__init__(message)
        self.temporary = temporary
        self.retry_after = retry_after
