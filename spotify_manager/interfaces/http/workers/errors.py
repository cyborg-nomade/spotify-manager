"""Original safe-boundary cancellation signals for HTTP workers."""


class _NewWineJobCancelledError(RuntimeError):
    """Stop one web flush while preserving the routine's durable state."""


class _NewKidsJobCancelledError(RuntimeError):
    """Stop one New Kids web job while preserving durable progress."""


class _Queue3JobCancelledError(RuntimeError):
    """Stop one Queue 3 web job while preserving durable progress."""


class _QueueJobCancelledError(RuntimeError):
    """Stop one Queue web job while preserving completed work."""


class _SauvignonJobCancelledError(RuntimeError):
    """Stop one Sauvignon recommendation job at a safe boundary."""


class _SlowListeningJobCancelledError(RuntimeError):
    """Stop one Slow Listening web flush at an interaction boundary."""


class _SomethingOldJobCancelledError(RuntimeError):
    """Stop one Something Old web job at an interaction or retry boundary."""


class _ReleaseCheckJobCancelledError(RuntimeError):
    """Stop one release-check job at an interaction or retry boundary."""


class _DiscographyJobCancelledError(RuntimeError):
    """Stop one discography job at an interaction or retry boundary."""


class _RequeueForADreamJobCancelledError(RuntimeError):
    """Stop one Requeue for a Dream job at an API or retry boundary."""


class _PalaceOfMemoryJobCancelledError(RuntimeError):
    """Stop one Palace of Memory job at an API or retry boundary."""
