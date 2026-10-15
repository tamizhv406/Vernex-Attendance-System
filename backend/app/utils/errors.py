"""What happens to an error nobody handled.

The person gets a plain sentence and a reference; what went wrong is written to the server's log
under that reference, in a form that is safe to keep: where it happened and what kind of error it
was, without the values that were being worked on. An error's own text is logged only for a
database error, whose first line names the constraint or the problem, and then with values taken out.
"""
import logging
import re
import secrets
import traceback

from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger("vernex.errors")

# An error's own text can quote the data it tripped over. These are taken out before it is logged.
_REDACTIONS = (
    # A password hash, whole: the parameters, the salt and the digest ("$argon2id$v=19$m=65536,t=3,p=4$...$...").
    (re.compile(r"\$(?:argon2(?:id|i|d)?|2[aby]|pbkdf2[\w-]*|scrypt)\$[^\s'\")]*"), "[hash]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[token]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [token]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:/@\s]+):[^@/\s]+@"), r"\1:[hidden]@"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|cookie|authorization)\b(\s*[=:]\s*)\S+"), r"\1\2[hidden]"),
    # Anything long and unbroken enough to be a key, a token or a digest.
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "[long value]"),
    # What a row holds about a person: an email address, a phone or ID number, and a value the
    # driver quotes after a colon (invalid input syntax for type integer: "STU-0042").
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\d{5,}"), "[number]"),
    (re.compile(r""":\s*(["'])[^"']*\1"""), ": [value]"),
)
MAX_LOGGED_TEXT = 300


def safe_error_text(error: BaseException) -> str:
    """What kind of error this was, in one line that is safe to log."""
    if not isinstance(error, SQLAlchemyError):
        # The text of any other error is whatever the code that raised it put in, and that can be
        # a name, an email or a phone number from the row being worked on. Its kind and where it
        # happened (where_it_happened) are what is kept.
        return type(error).__name__
    # The driver's first line only ("duplicate key value violates unique constraint ..."). The
    # statement, its values and PostgreSQL's DETAIL line, which quotes the row, are left out.
    text = str(getattr(error, "orig", None) or type(error).__name__)
    text = (text.strip().splitlines() or [""])[0][:MAX_LOGGED_TEXT]
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def where_it_happened(error: BaseException, frames: int = 6) -> str:
    # File, line and function of the last few steps. Lines of code, never the values in them.
    steps = traceback.extract_tb(error.__traceback__)[-frames:]
    return " <- ".join(f"{step.filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{step.lineno} {step.name}" for step in reversed(steps))


class ServerErrors:
    """Middleware: answers an unhandled error with a generic message, and logs it without its data.

    It sits inside the CORS middleware and nothing passes the error further up, so the web server
    never prints the original error, which for a database error would include the statement.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watching(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watching)
        except Exception as error:
            reference = secrets.token_hex(4)
            log.error("Unhandled error %s on %s %s: %s | at %s", reference, scope.get("method"), scope.get("path"), safe_error_text(error), where_it_happened(error))
            if started:
                # Part of an answer is already on its way; nothing more can be said to the client.
                return
            answer = JSONResponse(
                {"success": False, "message": f"Something went wrong on the server. If it keeps happening, give this reference to whoever looks after the system: {reference}", "details": {"reference": reference}},
                status_code=500,
            )
            await answer(scope, receive, send)
