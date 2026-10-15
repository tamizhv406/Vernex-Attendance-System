"""What the web server's access log may keep of a request: never the values in its query string.

uvicorn writes one line for every request, with the path and its query string as the browser sent
them. A query string can hold what someone typed (an email in the Admins search, a date range, an
ID), and the log is kept on disk. The names of the parameters stay, which is enough to tell one
request from another; the values are replaced.

    GET /super-admin/admins?search=asha%40example.com&role=admin
    GET /super-admin/admins?search=[hidden]&role=[hidden]
"""
import logging
import re

ACCESS_LOGGER = "uvicorn.access"
HIDDEN = "[hidden]"
# A parameter name looks like one. Anything else ("?asha@example.com", no "=") is a value itself.
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-\[\]]{0,40}")


def without_query_values(path: str) -> str:
    base, mark, query = path.partition("?")
    if not mark:
        return path
    parts = []
    for part in query.split("&"):
        if not part:
            continue
        name, equals, _value = part.partition("=")
        parts.append(f"{name}={HIDDEN}" if equals and _NAME.fullmatch(name) else HIDDEN)
    return f"{base}?{'&'.join(parts)}" if parts else base


class QueryValuesHidden(logging.Filter):
    """Rewrites uvicorn's access record, (client, method, path with query, http version, status), before it is written."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = args[:2] + (without_query_values(args[2]),) + args[3:]
        return True


def hide_query_values(logger_name: str = ACCESS_LOGGER) -> logging.Filter:
    """Puts the filter on uvicorn's access logger, once. Returns it."""
    logger = logging.getLogger(logger_name)
    for existing in logger.filters:
        if isinstance(existing, QueryValuesHidden):
            return existing
    hidden = QueryValuesHidden()
    logger.addFilter(hidden)
    return hidden
