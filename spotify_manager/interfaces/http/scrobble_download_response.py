"""Framework response owning a verified history file through delivery."""

from fastapi.responses import FileResponse
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from spotify_manager.application.scrobble_download import ScrobbleDownload


class ScrobbleHistoryResponse(FileResponse):
    """Keep a verified snapshot alive through streaming, then always release it.

    Args:
        snapshot: Independently owned, complete canonical history file.
    """

    def __init__(self, snapshot: ScrobbleDownload) -> None:
        """Present the original JSON bytes with their verified content identity.

        Args:
            snapshot: File and metadata retained until response completion.
        """
        self.snapshot = snapshot
        super().__init__(
            snapshot.path,
            media_type="application/json",
            filename=snapshot.metadata.filename,
            headers={
                "ETag": f'"{snapshot.metadata.sha256}"',
                "Cache-Control": "no-store",
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Release storage even when file delivery fails or is cancelled.

        Args:
            scope: Framework request metadata.
            receive: ASGI input callable required by the response protocol.
            send: ASGI output callable required by the response protocol.
        """
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.snapshot.close()
