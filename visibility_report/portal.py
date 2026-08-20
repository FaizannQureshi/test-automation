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


def parse_ga4_property_id(raw: str) -> str:
    """Extract GA4 property id from a bare id or analytics.google.com admin/report URL."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        return f"properties/{raw}"
    if raw.startswith("properties/"):
        return raw
    # https://analytics.google.com/...#/aACCOUNT_IDpPROPERTY_ID/...
    # Note: account+property are concatenated (a123p456) so \bp…\b does not match.
    m = (
        re.search(r"a\d+p(\d{6,})", raw)
        or re.search(r"[?/#&]p(\d{6,})", raw)
        or re.search(r"/p(\d{6,})", raw)
        or re.search(r"(?<![a-zA-Z0-9])p(\d{6,})", raw)
    )
    if m:
        return f"properties/{m.group(1)}"
    m2 = re.search(r"properties%2F(\d+)", raw) or re.search(r"properties/(\d+)", raw)
    if m2:
        return f"properties/{m2.group(1)}"
    digits = re.fullmatch(r"\d{6,}", raw)
    if digits:
        return f"properties/{raw}"
    return ""


def parse_gsc_site_url(raw: str) -> str:
    """Extract Search Console property URL from a GSC console link or bare site URL."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    # resource_id=https%3A%2F%2Fexample.com%2F  or  resource_id=sc-domain%3Aexample.com
    m = re.search(r"resource_id=([^&]+)", raw)
    if m:
        from urllib.parse import unquote

        return unquote(m.group(1)).strip()
    if "search-console" in raw and "://" in raw:
        # fallback: last path-looking host
        host_m = re.search(r"(?:sc-domain:)?([a-z0-9.-]+\.[a-z]{2,})", raw, re.I)
        if host_m and "google.com" not in host_m.group(1).lower():
            val = host_m.group(0)
            return val if val.startswith("sc-domain:") or val.startswith("http") else f"sc-domain:{host_m.group(1)}"
    return raw


def ga_property_from_client(client: dict) -> str:
    raw = custom_field_value(
        client,
        "GA4 Property ID",
        "Analytics Property ID",
        "Google Analytics Property ID",
        "GA4 URL",
        "Google Analytics URL",
        "Analytics URL",
        "analytics property id",
        "ga4 property id",
        "ga4 url",
    )
    if raw:
        parsed = parse_ga4_property_id(raw)
        if parsed:
            return parsed
    return analytics_property_id()


def gsc_site_from_client(client: dict) -> str | None:
    raw = custom_field_value(
        client,
        "Search Console Site URL",
        "Search Console Property",
        "GSC Site URL",
        "GSC URL",
        "Search Console URL",
        "search console site url",
        "gsc property",
        "gsc url",
    )
    if not raw:
        return None
    return parse_gsc_site_url(raw) or None


def list_clients() -> list[dict]:
    """Fetch portal clients (handles list or paginated dict responses)."""
    status, body = api_get("/clients")
    if status != 200:
        return []
    if isinstance(body, list):
        return [c for c in body if isinstance(c, dict)]
    if isinstance(body, dict):
        for key in ("clients", "data", "items", "results"):
            val = body.get(key)
            if isinstance(val, list):
                return [c for c in val if isinstance(c, dict)]
    return []


def find_client_by_website_host(host: str) -> dict | None:
    """Match a portal client whose Credentials → Website URL host matches."""
    want = host.lower().removeprefix("www.")
    for client in list_clients():
        site = website_url_from_client(client)
        if not site:
            continue
        if site_host(site) == want:
            return client
    return None


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

