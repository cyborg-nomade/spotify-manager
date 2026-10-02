"""Original health HTTP validation and job interactions."""

from dataclasses import dataclass


@dataclass(kw_only=True)
class HealthHandlers:
    """Validate and present one feature through explicit facade dependencies."""

    def health(self) -> dict[str, str]:
        """Liveness probe.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return {"status": "ok"}

    def auth_check(self) -> dict[str, str]:
        """Side-effect-free password check protected by the deployment middleware.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return {"status": "ok"}
