"""Headers on every answer of the backend (task S-07).

The backend only ever answers JSON or a file, never a page, so its policy can be the strictest
there is: nothing may be loaded or framed from an answer, browsers must not guess another content
type, no address leaks to another site, and no answer is kept in a browser or proxy cache (they
hold names, attendance and audit entries). The console's own pages get their headers from the web
server in front of it (deploy/Caddyfile).
"""

HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"cache-control", b"no-store"),
    (b"cross-origin-resource-policy", b"same-origin"),
)


class SecurityHeaders:
    """Middleware: adds HEADERS to every HTTP answer that does not set the header itself."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message):
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [(name, value) for name, value in HEADERS if name not in present]
            await send(message)

        await self.app(scope, receive, with_headers)
