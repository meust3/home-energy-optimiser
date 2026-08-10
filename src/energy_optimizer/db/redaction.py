"""Database connection-string display and defensive secret redaction."""

import re
from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

_URL_PATTERN = re.compile(
    r"(?P<scheme>(?:postgresql|postgres|sqlite)(?:\+[^:\s/]+)?://)"
    r"(?P<body>[^\s'\"]+)",
    re.IGNORECASE,
)


def safe_url(value: str | URL) -> URL:
    """Parse a URL without including its secret in parsing errors."""
    try:
        return make_url(value)
    except (ArgumentError, ValueError, TypeError):
        raise ValueError("Invalid DATABASE_URL (credentials redacted)") from None


def display_database_url(value: str | URL) -> str:
    """Return a useful target description that can never contain a password."""
    url = safe_url(value)
    if url.get_backend_name() == "sqlite":
        return f"sqlite database={url.database or ':memory:'}"
    parts = [f"backend={url.get_backend_name()}"]
    if url.username:
        parts.append(f"username={url.username}")
    if url.host:
        parts.append(f"host={url.host}")
    if url.port:
        parts.append(f"port={url.port}")
    if url.database:
        parts.append(f"database={url.database}")
    return " ".join(parts)


def redact_database_urls(value: Any) -> str:
    """Redact credentials from arbitrary diagnostic text."""
    text = str(value)

    def replace(match: re.Match[str]) -> str:
        try:
            return safe_url(match.group(0)).render_as_string(hide_password=True)
        except ValueError:
            return f"{match.group('scheme')}<redacted>"

    return _URL_PATTERN.sub(replace, text)
