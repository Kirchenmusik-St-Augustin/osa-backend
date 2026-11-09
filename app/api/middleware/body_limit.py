"""Pure ASGI middleware that rejects oversized request bodies before any
other middleware or route reads them into memory.

RequestLoggingMiddleware (and Starlette's own body parsing) buffer a whole
request body, so without a ceiling a single unauthenticated request with a
multi-gigabyte body exhausts the container's memory. The limit is enforced
twice: against the declared Content-Length (cheap rejection before any data
is read) and against the bytes actually received (chunked bodies carry no
Content-Length)."""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.status import HTTP_413_CONTENT_TOO_LARGE
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_TOO_LARGE_DETAIL = "Die Anfrage ist zu groß."


class _BodyTooLargeError(Exception):
    """Raised from the wrapped receive() once the byte ceiling is crossed."""


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._declared_length_exceeds_limit(scope):
            await self._reject(scope, receive, send)
            return

        await self._forward_with_byte_limit(scope, receive, send)

    def _declared_length_exceeds_limit(self, scope: Scope) -> bool:
        declared_length = Headers(scope=scope).get("content-length")
        if declared_length is None or not declared_length.isdigit():
            return False
        return int(declared_length) > self.max_body_bytes

    async def _forward_with_byte_limit(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] != "http.request":
                return message
            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_body_bytes:
                raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not response_started:
                await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": _TOO_LARGE_DETAIL},
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)
