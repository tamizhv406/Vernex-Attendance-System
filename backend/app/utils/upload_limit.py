"""How big a camera frame may be before the backend reads it.

A frame from the console is a JPEG of a few kilobytes. Without a limit, anyone logged in could send
a body as large as the server's memory, and the face routes would read all of it. The length is
checked before a byte of the body is read; the web server never delivers more than the length the
request declared, and a request that declares none (sent in chunks) is refused.
"""
import json


class UploadLimit:
    """Middleware: answers 413 for a body over `limit` bytes, and 411 for one of unknown length, on
    the paths that start with one of `prefixes`."""

    def __init__(self, app, limit: int, prefixes: tuple = ("/face/",)):
        self.app = app
        self.limit = limit
        self.prefixes = prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith(self.prefixes):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is None:
            if b"chunked" in headers.get(b"transfer-encoding", b"").lower():
                await refuse(send, 411, "Send the frame with its length (Content-Length).")
                return
        else:
            try:
                size = int(declared)
            except ValueError:
                size = -1
            if size < 0 or size > self.limit:
                await refuse(send, 413, f"The frame is too large. At most {self.limit // 1000:,} kB is accepted.")
                return
        await self.app(scope, receive, send)


async def refuse(send, status: int, detail: str):
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
