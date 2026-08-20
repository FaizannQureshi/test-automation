"""Runtime secret helpers. Never log secret values."""

from __future__ import annotations

import os

# v1 Cloud env secret names (lowercase) + legacy uppercase aliases.
_SERVICE_KEYS: dict[str, tuple[str, ...]] = {
    "PAGESPEED": ("pagespeed_api", "PAGESPEED_API", "GOOGLE_PAGESPEED_API_KEY", "GOOGLE_API_KEY"),
    "PLACES": ("places_api", "PLACES_API", "GOOGLE_PLACES_API_KEY", "GOOGLE_API_KEY"),
    "GEOCODING": ("geocoding_api", "GEOCODING_API", "GOOGLE_GEOCODING_API_KEY", "GOOGLE_API_KEY"),
    "CUSTOM_SEARCH": (
        "custom_search_api",
        "CUSTOM_SEARCH_API",
        "GOOGLE_CUSTOM_SEARCH_API_KEY",
        "GOOGLE_API_KEY",
    ),
}


def env(*keys: str) -> str:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def google_key(service: str = "") -> str:
    if service:
        return env(*_SERVICE_KEYS.get(service.upper(), ("GOOGLE_API_KEY",)))
    return env("GOOGLE_API_KEY")


def gemini_key() -> str:
    return env(
        "gemini_api",
        "GEMINI_API",
        "GEMINI_API_KEY",
        "GOOGLE_GEMINI_API_KEY",
    )


def cse_id() -> str:
    return env("GOOGLE_CSE_ID", "GOOGLE_CUSTOM_SEARCH_ENGINE_ID")


def gsc_secret() -> str:
    return env(
        "search_console_api",
        "SEARCH_CONSOLE_API",
        "GOOGLE_SEARCH_CONSOLE_CREDENTIALS_JSON",
        "GSC_CREDENTIALS_JSON",
    )


def ga_secret() -> str:
    return env(
        "analytics_data_api",
        "ANALYTICS_DATA_API",
        "GOOGLE_ANALYTICS_CREDENTIALS_JSON",
        "GA_CREDENTIALS_JSON",
    )


def analytics_property_id() -> str:
    raw = env(
        "analytics_property_id",
        "GOOGLE_ANALYTICS_PROPERTY_ID",
        "GA4_PROPERTY_ID",
    )
    if not raw:
        return ""
    raw = raw.strip()
    if raw.isdigit():
        return f"properties/{raw}"
    if not raw.startswith("properties/"):
        return f"properties/{raw}"
    return raw


def gsc_configured() -> bool:
    return bool(gsc_secret())


def ga_configured() -> bool:
    return bool(ga_secret()) and bool(analytics_property_id())
