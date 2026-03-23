"""Metadata import from supported page URLs."""
from __future__ import annotations

from urllib.parse import urlparse

from .types import DiscInfo, Metadata
from . import bandcamp

_SUPPORTED_PROVIDERS = {"Bandcamp"}


def lookup_url(
    url: str,
    *,
    disc_info: DiscInfo | None = None,
    timeout: int = 15,
    debug: bool = False,
) -> list[Metadata]:
    """Route a metadata URL to the appropriate site-specific importer."""
    provider = provider_name(url)
    if provider == "Bandcamp":
        return bandcamp.lookup_url(
            url,
            disc_info=disc_info,
            timeout=timeout,
            debug=debug,
        )
    if provider:
        raise ValueError(f"Unsupported metadata URL provider: {provider}")
    raise ValueError("Unsupported metadata URL.")


def provider_name(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    if host.endswith("bandcamp.com"):
        return "Bandcamp"
    if host:
        return host
    return ""


def is_supported_url(url: str) -> bool:
    return provider_name(url) in _SUPPORTED_PROVIDERS
