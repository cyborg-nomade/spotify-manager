"""Bind lifespan-owned async resources across one ASGI request."""

from dataclasses import dataclass

from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from spotify_manager.bootstrap.execution import ExecutionBinding


@dataclass
class ExecutionMiddleware:
    """Connect FastAPI's request task to its existing lifespan resource owner.

    Args:
        app: Next ASGI application required by the framework middleware contract.
    """

    app: ASGIApp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Deliver a request within its lifespan scope, leaving other ASGI events alone.

        Args:
            scope: Framework request or lifespan metadata.
            receive: Framework input channel.
            send: Framework output channel.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with ExecutionBinding(scope["app"].state.execution):
            await self.app(scope, receive, send)
