"""Network guard: the app may only contact hosts listed in app/adapters/registry.py."""

from urllib.parse import urlparse

from app.adapters.registry import allowed_hosts
from app.errors import FriendlyError


def check_url_allowed(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed_hosts():
        raise FriendlyError(
            f"The app tried to contact '{host}', which is not an approved data source.",
            "This is a safety stop. Tell Claude which screen you were on so the source can "
            "be reviewed and added to DATA_SOURCES.md, or removed.",
        )
