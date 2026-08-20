"""Connection Inc portal API and client field helpers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from .config import API
from .env import analytics_property_id, env

def api_headers() -> dict[str, str]:
    key = env("PORTAL_API_KEY")
    if not key:
        raise SystemExit("PORTAL_API_KEY is not set")
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ConnectionInc-WeeklySEO/2.0",
    }


def api_get(path: str) -> tuple[int, Any]:
    r = requests.get(API + path, headers=api_headers(), timeout=30)
    try:
        body = r.json()
    except Exception:
        body = {"error": r.text[:500]}
    return r.status_code, body


def api_send(method: str, path: str, payload: dict) -> tuple[int, Any]:
    r = requests.request(
        method,
        API + path,
        headers=api_headers(),
        json=payload,
        timeout=60,
    )
    try:
        body = r.json()
    except Exception:
        body = {"error": r.text[:800], "raw_len": len(r.text)}
    return r.status_code, body


def website_url_from_client(client: dict) -> str | None:
    for field in client.get("customFields") or []:
        cat = ((field.get("category") or {}).get("name") or "").strip().lower()
        name = (field.get("name") or "").strip().lower()
        if cat == "credentials" and name == "website url":
            val = (field.get("value") or "").strip()
            return val or None
    return None


def custom_field_value(client: dict, *names: str) -> str | None:
    """Find a custom field value by case-insensitive name (any category)."""
    wanted = {n.strip().lower() for n in names}
    for field in client.get("customFields") or []:
        name = (field.get("name") or "").strip().lower()
        if name in wanted:
            val = (field.get("value") or "").strip()
            if val:
                return val
    return None


def ga_property_from_client(client: dict) -> str:
    raw = custom_field_value(
        client,
        "GA4 Property ID",
        "Analytics Property ID",
        "Google Analytics Property ID",
        "analytics property id",
        "ga4 property id",
    )
    if not raw:
        return analytics_property_id()
    raw = raw.strip()
    if raw.isdigit():
        return f"properties/{raw}"
    if not raw.startswith("properties/"):
        return f"properties/{raw}"
    return raw


def gsc_site_from_client(client: dict) -> str | None:
    return custom_field_value(
        client,
        "Search Console Site URL",
        "Search Console Property",
        "GSC Site URL",
        "search console site url",
        "gsc property",
    )


def normalize_gsc_site(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("sc-domain:"):
        return raw
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw if raw.endswith("/") else raw + "/"
    if "." in raw and not raw.startswith("sc-domain:"):
        host = raw.removeprefix("www.")
        return f"sc-domain:{host}"
    return raw


def normalize_site_url(raw: str) -> str:
    raw = raw.strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )


def origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def site_host(url: str) -> str:
    return (urlparse(url).netloc or url).lower().removeprefix("www.")

