"""Google and Gemini API clients used by the weekly audit."""

from __future__ import annotations

import json
import re
import time
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import requests

from .config import TODAY
from .env import (
    analytics_property_id,
    env,
    ga_secret,
    gemini_key,
    google_key,
    gsc_secret,
)
from .portal import normalize_gsc_site, site_host

def pagespeed(url: str, *, strategy: str = "mobile") -> dict:
    key = google_key("PAGESPEED")
    if not key:
        return {"ok": False, "error": "pagespeed_api not set"}
    try:
        r = requests.get(
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            params={"url": url, "key": key, "strategy": strategy, "category": "performance"},
            timeout=90,
        )
        data = r.json()
        if r.status_code != 200:
            err = data.get("error", {}).get("message", r.text[:200])
            return {"ok": False, "error": err}
        lh = data.get("lighthouseResult", {})
        audits = lh.get("audits", {})
        cats = lh.get("categories", {})
        perf = int(round((cats.get("performance") or {}).get("score", 0) * 100))
        lcp = audits.get("largest-contentful-paint", {}).get("displayValue", "")
        cls = audits.get("cumulative-layout-shift", {}).get("displayValue", "")
        tbt = audits.get("total-blocking-time", {}).get("displayValue", "")
        lcp_ms = audits.get("largest-contentful-paint", {}).get("numericValue")
        cls_num = audits.get("cumulative-layout-shift", {}).get("numericValue")
        return {
            "ok": True,
            "strategy": strategy,
            "performance": perf,
            "lcp": lcp,
            "lcp_ms": lcp_ms,
            "cls": cls,
            "cls_num": cls_num,
            "tbt": tbt,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def parse_search_verdict(text: str, host: str) -> tuple[bool, int | None, list[str]]:
    """Parse Gemini search-grounding reply for presence, position, competitor hosts."""
    host_clean = site_host(host)
    low = text.lower()
    found = host_clean in low or host.lower() in low
    pos: int | None = None
    m = re.search(r"POSITION[=:\s]+(\d+)", text, re.I)
    if m:
        pos = int(m.group(1))
    elif re.search(r"POSITION[=:\s]+none", text, re.I):
        pos = None
    elif found:
        for line in text.splitlines():
            if host_clean in line.lower():
                pm = re.search(r"\b(\d{1,2})\b", line)
                if pm:
                    pos = int(pm.group(1))
                    break
    competitors: list[str] = []
    for dom in re.findall(r"(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9.-]+\.[a-z]{2,})", low):
        d = dom.removeprefix("www.")
        if d != host_clean and d not in competitors and not d.endswith("." + host_clean):
            competitors.append(d)
    return found, pos, competitors[:5]


def gemini_search_ranking(query: str, brand: str, host: str) -> dict:
    """Sample Google search visibility via Gemini + Google Search grounding."""
    prompt = (
        f'Search Google for: "{query}"\n\n'
        f"Does {host} (business: {brand}) appear in the first 20 organic results?\n"
        "Reply with exactly these lines first:\n"
        "FOUND=yes or FOUND=no\n"
        "POSITION=<number 1-20 or none>\n"
        "Then briefly note up to 5 other domains that ranked instead."
    )
    resp = gemini_ask(prompt, use_search=True)
    text = resp.get("text") or ""
    found, pos, competitors = parse_search_verdict(text, host)
    return {
        "ok": resp.get("ok", False),
        "text": text,
        "found": found,
        "position": pos,
        "competitors": competitors,
        "grounding_urls": resp.get("grounding_urls") or [],
    }


def places_lookup(business_name: str, website: str) -> dict:
    key = google_key("PLACES")
    if not key:
        return {"ok": False, "error": "places_api not set"}
    host = site_host(website)
    query = business_name or host
    try:
        r = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": (
                    "places.displayName,places.formattedAddress,places.rating,"
                    "places.userRatingCount,places.websiteUri,places.nationalPhoneNumber,"
                    "places.types,places.googleMapsUri"
                ),
            },
            json={"textQuery": query, "pageSize": 5},
            timeout=30,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        places = r.json().get("places") or []
        match = None
        for p in places:
            uri = (p.get("websiteUri") or "").lower()
            if host in uri or not uri:
                match = p
                if host in uri:
                    break
        if not match and places:
            match = places[0]
        if not match:
            return {"ok": False, "error": "No listing found"}
        return {
            "ok": True,
            "name": (match.get("displayName") or {}).get("text") or business_name,
            "address": match.get("formattedAddress") or "",
            "rating": match.get("rating"),
            "review_count": match.get("userRatingCount"),
            "phone": match.get("nationalPhoneNumber") or "",
            "website": match.get("websiteUri") or "",
            "types": match.get("types") or [],
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def geocode_address(address: str) -> dict:
    key = google_key("GEOCODING")
    if not key or not address:
        return {"ok": False}
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key},
            timeout=20,
        )
        data = r.json()
        if data.get("status") != "OK":
            return {"ok": False}
        loc = data["results"][0]
        return {"ok": True, "formatted": loc.get("formatted_address"), "place_id": loc.get("place_id")}
    except Exception:
        return {"ok": False}


def gemini_ask(prompt: str, *, use_search: bool = False) -> dict:
    key = gemini_key()
    if not key:
        return {"ok": False, "error": "gemini_api not set", "text": "", "grounding_urls": []}
    model = env("GEMINI_MODEL") or "gemini-3.6-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    if use_search:
        body["tools"] = [{"google_search": {}}]
    try:
        r = requests.post(url, params={"key": key}, json=body, timeout=90)
        data = r.json()
        if r.status_code != 200:
            err = data.get("error", {}).get("message", r.text[:200])
            return {"ok": False, "error": err, "text": "", "grounding_urls": []}
        candidate = data.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [{}])
        text = parts[0].get("text", "") if parts else ""
        grounding_urls: list[str] = []
        for chunk in (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []:
            uri = (chunk.get("web") or {}).get("uri")
            if uri:
                grounding_urls.append(uri)
        return {"ok": True, "text": text, "error": None, "grounding_urls": grounding_urls}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "text": "", "grounding_urls": []}


# ---------------------------------------------------------------------------
# Search Console + Google Analytics (OAuth via secret — API key or service account JSON)
# ---------------------------------------------------------------------------

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


def _access_token_for_secret(secret: str, scopes: list[str]) -> tuple[str | None, str | None]:
    """Obtain a bearer token from search_console_api / analytics_data_api secret."""
    secret = (secret or "").strip()
    if not secret:
        return None, "secret not set"

    # Service account JSON stored in the Runtime Secret
    if secret.startswith("{"):
        try:
            info = json.loads(secret)
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as GoogleAuthRequest

            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            creds.refresh(GoogleAuthRequest())
            return creds.token, None
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:160]}"

    # Plain GCP API key — Google does not accept API keys alone for GSC / GA4 data access.
    return (
        None,
        "Plain API keys are not supported for Search Console / Analytics data. "
        "Store service account JSON in search_console_api / analytics_data_api, "
        "and grant that service account access to the property.",
    )


def gsc_site_url_candidates(site_url: str) -> list[str]:
    host = site_host(site_url)
    parsed = urlparse(site_url)
    base_https = urlunparse(("https", parsed.netloc.lower(), "/", "", "", ""))
    candidates = [
        f"sc-domain:{host}",
        base_https,
        f"https://{host}/",
        f"https://www.{host}/",
        site_url.rstrip("/") + "/",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def fetch_search_console(site_url: str, *, gsc_override: str | None = None) -> dict:
    secret = gsc_secret()
    if not secret:
        return {"ok": False, "error": "search_console_api not set", "queries": []}
    token, err = _access_token_for_secret(secret, [GSC_SCOPE])
    if not token:
        return {"ok": False, "error": err or "auth failed", "queries": []}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        sites_resp = requests.get(
            "https://www.googleapis.com/webmasters/v3/sites",
            headers=headers,
            timeout=30,
        )
        if sites_resp.status_code != 200:
            return {
                "ok": False,
                "error": f"sites list HTTP {sites_resp.status_code}",
                "queries": [],
            }
        site_entries = sites_resp.json().get("siteEntry") or []
        permitted = {e.get("siteUrl") for e in site_entries if e.get("siteUrl")}
        chosen = None
        if gsc_override:
            override = normalize_gsc_site(gsc_override)
            if override in permitted:
                chosen = override
            else:
                host = site_host(override.replace("sc-domain:", "https://" + override.split(":", 1)[-1]))
                for p in permitted:
                    if host in p or override in p:
                        chosen = p
                        break
        if not chosen:
            for candidate in gsc_site_url_candidates(site_url):
                if candidate in permitted:
                    chosen = candidate
                    break
        if not chosen and permitted:
            host = site_host(site_url)
            for p in permitted:
                if host in p:
                    chosen = p
                    break
        if not chosen:
            available = ", ".join(sorted(permitted)[:6]) if permitted else "none"
            return {
                "ok": False,
                "error": (
                    f"No matching Search Console property for {site_url}. "
                    f"Properties this service account can access: {available}. "
                    "Add the service account email in Search Console → Settings → Users, "
                    "or set a client custom field Search Console Site URL to the exact property "
                    "(e.g. sc-domain:example.com or https://www.example.com/)."
                ),
                "queries": [],
                "available_properties": sorted(permitted),
            }
        end = TODAY - timedelta(days=1)
        start = end - timedelta(days=27)
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["query"],
            "rowLimit": 15,
        }
        q_resp = requests.post(
            f"https://www.googleapis.com/webmasters/v3/sites/{quote(chosen, safe='')}/searchAnalytics/query",
            headers={**headers, "Content-Type": "application/json"},
            json=body,
            timeout=45,
        )
        if q_resp.status_code != 200:
            return {
                "ok": False,
                "error": f"searchAnalytics HTTP {q_resp.status_code}",
                "queries": [],
                "siteUrl": chosen,
            }
        rows = q_resp.json().get("rows") or []
        queries = []
        for row in rows:
            keys = row.get("keys") or []
            query = keys[0] if keys else ""
            pos = row.get("position")
            queries.append(
                {
                    "query": query,
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "position": round(pos, 1) if pos is not None else None,
                    "ctr": row.get("ctr"),
                }
            )
        total_clicks = sum(q.get("clicks", 0) for q in queries)
        total_impressions = sum(q.get("impressions", 0) for q in queries)
        return {
            "ok": True,
            "error": None,
            "siteUrl": chosen,
            "queries": queries,
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "period": f"{start.isoformat()} to {end.isoformat()}",
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "queries": []}


def fetch_analytics(property_id: str | None = None) -> dict:
    secret = ga_secret()
    prop = (property_id or "").strip() or analytics_property_id()
    if not secret:
        return {"ok": False, "error": "analytics_data_api not set"}
    if not prop:
        return {"ok": False, "error": "analytics_property_id not set (env or client GA4 Property ID custom field)"}
    token, err = _access_token_for_secret(secret, [GA_SCOPE])
    if not token:
        return {"ok": False, "error": err or "auth failed"}
    end = TODAY - timedelta(days=1)
    start = end - timedelta(days=27)
    body = {
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "metrics": [{"name": "sessions"}, {"name": "activeUsers"}, {"name": "screenPageViews"}],
    }
    try:
        r = requests.post(
            f"https://analyticsdata.googleapis.com/v1beta/{prop}:runReport",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=45,
        )
        if r.status_code != 200:
            hint = ""
            if r.status_code == 403:
                hint = (
                    " — grant the service account email Viewer access on this GA4 property "
                    "(Admin → Property access management) and enable Google Analytics Data API in GCP."
                )
            return {"ok": False, "error": f"runReport HTTP {r.status_code}{hint}", "property": prop}
        data = r.json()
        values = []
        if data.get("rows"):
            values = data["rows"][0].get("metricValues") or []
        sessions = int(values[0].get("value", "0")) if len(values) > 0 else 0
        users = int(values[1].get("value", "0")) if len(values) > 1 else 0
        pageviews = int(values[2].get("value", "0")) if len(values) > 2 else 0
        return {
            "ok": True,
            "error": None,
            "property": prop,
            "sessions": sessions,
            "active_users": users,
            "pageviews": pageviews,
            "period": f"{start.isoformat()} to {end.isoformat()}",
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def brand_mentioned(text: str, brand: str, host: str) -> bool:
    low = text.lower()
    return brand.lower() in low or host.lower() in low


def owned_citations(text: str, host: str) -> bool:
    host = host.lower().removeprefix("www.")
    return host in text.lower()

