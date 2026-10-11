"""Bound private assessment inputs before JSON parsing; never echo rejected evidence."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BYTES = 3 * 1024**2


def private_input(path: str) -> bool:
    return (
        path.startswith("/api/assessments")
        or path.startswith("/api/conversations")
        or path.startswith("/api/assessment-jobs")
        or path in {"/api/projects/prompt", "/api/projects/review"}
        or (path.startswith("/api/runs/") and path.endswith("/ask"))
    )


class AssessmentInputBounds:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not private_input(scope["path"]):
            await self.app(scope, receive, send)
            return
        data = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(data) + len(chunk) > MAX_REQUEST_BYTES:
                await JSONResponse(
                    {"detail": "Private assessment request exceeds the bounded input limit."},
                    status_code=413,
                )(scope, receive, send)
                return
            data.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(data), "more_body": False}

        await self.app(scope, bounded, send)
