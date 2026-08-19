#!/usr/bin/env python3
"""Weekly Connection Inc client visibility snapshot. Never prints secrets."""

from __future__ import annotations

import html as htmlmod
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://seo.connectionincorporated.com/api/v1"
UA = (
    "Mozilla/5.0 (compatible; ConnectionIncWeeklySEO/2.0; "
    "+https://seo.connectionincorporated.com)"
)
TIMEOUT = 25
TODAY = date.today()
REPORT_DATE = TODAY.isoformat()
WEEK_OF = (TODAY - timedelta(days=TODAY.weekday())).isoformat()

# Single active pilot while the new visibility template is verified in Admin → Reports.
PILOTS = [
    ("Adam Zeman", "cmkoitqae0001ib04j8hrefa9"),
]

# ---------------------------------------------------------------------------
# Environment helpers (never log values)
# ---------------------------------------------------------------------------


def env(*keys: str) -> str:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


# v1 Cloud env secret names (lowercase) + legacy uppercase aliases.
_SERVICE_KEYS: dict[str, tuple[str, ...]] = {
    "PAGESPEED": ("pagespeed_api", "GOOGLE_PAGESPEED_API_KEY", "GOOGLE_API_KEY"),
    "PLACES": ("places_api", "GOOGLE_PLACES_API_KEY", "GOOGLE_API_KEY"),
    "GEOCODING": ("geocoding_api", "GOOGLE_GEOCODING_API_KEY", "GOOGLE_API_KEY"),
    "CUSTOM_SEARCH": ("custom_search_api", "GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_API_KEY"),
}


def google_key(service: str = "") -> str:
    if service:
        return env(*_SERVICE_KEYS.get(service.upper(), ("GOOGLE_API_KEY",)))
    return env("GOOGLE_API_KEY")


def gemini_key() -> str:
    return env("gemini_api", "GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY")


def cse_id() -> str:
    return env("GOOGLE_CSE_ID", "GOOGLE_CUSTOM_SEARCH_ENGINE_ID")


def gsc_configured() -> bool:
    return bool(env("GOOGLE_SEARCH_CONSOLE_CREDENTIALS_JSON", "GSC_CREDENTIALS_JSON"))


def ga_configured() -> bool:
    return bool(env("GOOGLE_ANALYTICS_PROPERTY_ID", "GA4_PROPERTY_ID"))


# ---------------------------------------------------------------------------
# Portal API
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# HTTP / HTML parsing
# ---------------------------------------------------------------------------


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self._in_title = False
        self._in_heading: str | None = None
        self._heading_parts: list[str] = []
        self.headings: list[tuple[str, str]] = []
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.h1_count = 0
        self._in_script = False
        self.json_ld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "script":
            self._in_script = True
            if ad.get("type", "").lower() == "application/ld+json":
                self._json_ld_buf: list[str] = []
        elif tag == "meta":
            self.metas.append(ad)
        elif tag == "link":
            self.links.append(ad)
        elif tag == "img":
            self.images.append(ad)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if tag == "h1":
                self.h1_count += 1
            self._in_heading = tag
            self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_script:
            self._in_script = False
            if hasattr(self, "_json_ld_buf"):
                blob = "".join(self._json_ld_buf).strip()
                if blob:
                    self.json_ld.append(blob)
                del self._json_ld_buf
        if tag == self._in_heading:
            text = re.sub(r"\s+", " ", "".join(self._heading_parts)).strip()
            self.headings.append((tag, text))
            self._in_heading = None
            self._heading_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_heading:
            self._heading_parts.append(data)
        if self._in_script and hasattr(self, "_json_ld_buf"):
            self._json_ld_buf.append(data)


def meta_content(parser: PageParser, *, name: str | None = None, prop: str | None = None) -> str:
    for m in parser.metas:
        if name and m.get("name", "").lower() == name.lower():
            return (m.get("content") or "").strip()
        if prop and m.get("property", "").lower() == prop.lower():
            return (m.get("content") or "").strip()
    return ""


def canonical_href(parser: PageParser) -> str:
    for link in parser.links:
        rel = (link.get("rel") or "").lower().split()
        if "canonical" in rel:
            return (link.get("href") or "").strip()
    return ""


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    adapter = HTTPAdapter(max_retries=Retry(total=0))
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def fetch(s: requests.Session, url: str, *, allow_redirects: bool = True) -> dict:
    started = time.monotonic()
    try:
        r = s.get(url, timeout=TIMEOUT, allow_redirects=allow_redirects, verify=True)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": True,
            "error": None,
            "status": r.status_code,
            "url": r.url,
            "elapsed_ms": elapsed_ms,
            "text": r.text if len(r.content) < 2_500_000 else r.text[:1_000_000],
            "headers": {k.lower(): v for k, v in r.headers.items()},
            "content_type": (r.headers.get("Content-Type") or ""),
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}"[:300],
            "status": None,
            "url": url,
            "elapsed_ms": elapsed_ms,
            "text": "",
            "headers": {},
            "content_type": "",
        }


def robots_blocks_all(text: str) -> bool:
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines()]
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for ln in lines:
        if not ln or ln.startswith("#"):
            continue
        if ln.lower().startswith("user-agent:"):
            ua = ln.split(":", 1)[1].strip()
            if current is None or current["disallows"] or current["allows"]:
                current = {"agents": [ua], "disallows": [], "allows": []}
                groups.append(current)
            else:
                current["agents"].append(ua)
            continue
        if current is None:
            continue
        if ln.lower().startswith("disallow:"):
            current["disallows"].append(ln.split(":", 1)[1].strip())
        elif ln.lower().startswith("allow:"):
            current["allows"].append(ln.split(":", 1)[1].strip())
    for g in groups:
        agents = [a.lower() for a in g["agents"]]
        if "*" in agents or "googlebot" in agents:
            if "/" in g["disallows"] and not g["allows"]:
                return True
    return False


def sitemap_urls_from_robots(text: str) -> list[str]:
    out = []
    for ln in (text or "").splitlines():
        if ln.strip().lower().startswith("sitemap:"):
            url = ln.split(":", 1)[1].strip()
            if url:
                out.append(url)
    return out


def looks_like_xml_sitemap(text: str, content_type: str) -> bool:
    blob = (text or "")[:4000].lower()
    ct = (content_type or "").lower()
    if "html" in ct and "<urlset" not in blob and "<sitemapindex" not in blob:
        return False
    return ("<urlset" in blob) or ("<sitemapindex" in blob)


def count_sitemap_urls(s: requests.Session, sitemap_url: str, *, depth: int = 0) -> tuple[int, list[str]]:
    """Return URL count and up to 30 page URLs from sitemap(s)."""
    if depth > 2:
        return 0, []
    res = fetch(s, sitemap_url)
    if not res["ok"] or res["status"] != 200:
        return 0, []
    text = res["text"] or ""
    page_urls: list[str] = []
    total = 0
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return 0, []
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag == "sitemapindex":
        for sm in root.findall(".//{*}sitemap/{*}loc"):
            if sm.text:
                sub_count, sub_urls = count_sitemap_urls(s, sm.text.strip(), depth=depth + 1)
                total += sub_count
                page_urls.extend(sub_urls)
    elif tag == "urlset":
        for loc in root.findall(".//{*}url/{*}loc"):
            if loc.text:
                total += 1
                if len(page_urls) < 30:
                    page_urls.append(loc.text.strip())
    return total, page_urls


def schema_types(json_ld_blocks: list[str]) -> set[str]:
    types: set[str] = set()
    for blob in json_ld_blocks:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                t = item.get("@type")
                if isinstance(t, str):
                    types.add(t)
                elif isinstance(t, list):
                    types.update(x for x in t if isinstance(x, str))
                for v in item.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(item, list):
                stack.extend(item)
    return types


def service_like_pages(headings: list[tuple[str, str]], page_urls: list[str], host: str) -> list[str]:
    keywords = ("service", "product", "solution", "offer", "about")
    picked: list[str] = []
    for url in page_urls:
        low = url.lower()
        if site_host(low) != host:
            continue
        if any(k in low for k in keywords) and url not in picked:
            picked.append(url)
    for tag, text in headings:
        if tag in ("h2", "h3") and text and len(picked) < 3:
            slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
            if slug:
                guess = f"https://{host}/{slug}"
                if guess not in picked:
                    picked.append(guess)
    return picked[:3]


# ---------------------------------------------------------------------------
# External APIs
# ---------------------------------------------------------------------------


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
    model = env("GEMINI_MODEL") or "gemini-2.0-flash"
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


def brand_mentioned(text: str, brand: str, host: str) -> bool:
    low = text.lower()
    return brand.lower() in low or host.lower() in low


def owned_citations(text: str, host: str) -> bool:
    host = host.lower().removeprefix("www.")
    return host in text.lower()


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------


def build_search_queries(business: str, host: str, headings: list[tuple[str, str]]) -> list[str]:
    brand = business.strip() or host.split(".")[0].replace("-", " ").title()
    queries = [brand, f"{brand} {host.split('.')[0]}"]
    services: list[str] = []
    for tag, text in headings:
        if tag in ("h2", "h3") and 4 < len(text) < 80:
            services.append(text.strip())
    for svc in services[:6]:
        queries.append(svc)
        queries.append(f"{svc} near me")
    # Pad to 10 with category-style queries
    while len(queries) < 10:
        queries.append(f"best {brand.split()[0]} services")
    return queries[:10]


def build_ai_prompts(business: str, host: str, queries: list[str]) -> list[str]:
    brand = business.strip() or host
    prompts = [
        f"What is {brand}?",
        f"Tell me about {brand} ({host}).",
    ]
    for q in queries[2:10]:
        prompts.append(f"Who is the best provider for: {q}?")
    return prompts[:10]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def clamp_score(n: float) -> int:
    return max(0, min(100, int(round(n))))


def metric_status(kind: str, value: float | None, *, good: float, warn: float | None = None) -> str:
    if value is None:
        return "Watch"
    if kind == "lower_is_better":
        if value <= good:
            return "On track"
        if warn is not None and value <= warn:
            return "Watch"
        return "Fix"
    # higher_is_better
    if value >= good:
        return "On track"
    if warn is not None and value >= warn:
        return "Watch"
    return "Fix"


def score_from_ratio(found: int, total: int) -> int:
    if total <= 0:
        return 0
    return clamp_score(found / total * 100)


# ---------------------------------------------------------------------------
# Full visibility audit
# ---------------------------------------------------------------------------


def audit_visibility(site_url: str, business_name: str) -> dict:
    s = session()
    host = site_host(site_url)
    brand = business_name.strip() or host.split(".")[0].replace("-", " ").title()

    homepage = fetch(s, site_url)
    reachable = bool(homepage["ok"] and homepage["status"] and homepage["status"] < 400)
    parser = PageParser()
    title = meta_desc = canonical = ""
    if homepage["ok"] and homepage["text"]:
        try:
            parser.feed(homepage["text"])
        except Exception:
            pass
        title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
        meta_desc = meta_content(parser, name="description")
        canonical = canonical_href(parser)

    final_url = homepage.get("url") or site_url
    base = origin(final_url if homepage["ok"] else site_url)

    # robots + sitemap
    robots = fetch(s, base + "/robots.txt")
    robots_text = robots["text"] if robots["ok"] and robots["status"] == 200 else ""
    robots_blocked = robots_blocks_all(robots_text)
    sitemap_candidates = sitemap_urls_from_robots(robots_text)
    if base + "/sitemap.xml" not in sitemap_candidates:
        sitemap_candidates.append(base + "/sitemap.xml")
    sitemap_url = None
    sitemap_count = 0
    page_urls: list[str] = []
    for su in sitemap_candidates:
        cnt, urls = count_sitemap_urls(s, su)
        if cnt > 0:
            sitemap_url = su
            sitemap_count = cnt
            page_urls = urls
            break

    schema = schema_types(parser.json_ld)
    service_pages = service_like_pages(parser.headings, page_urls, host)
    extra_ps_urls = [u for u in service_pages if u != final_url][:2]

    # PageSpeed
    ps_home_m = pagespeed(final_url, strategy="mobile")
    ps_home_d = pagespeed(final_url, strategy="desktop")
    ps_extra: list[dict] = []
    for u in extra_ps_urls:
        ps_extra.append({"url": u, **pagespeed(u, strategy="mobile")})

    # Search sample via Gemini + Google Search grounding
    queries = build_search_queries(brand, host, parser.headings)
    search_obs: list[dict] = []
    competitors: dict[str, str] = {}
    first_page_hits = 0
    search_method = "Gemini + Google Search grounding"
    if not gemini_key():
        search_method = "Unavailable (gemini_api not set)"
    for q in queries:
        if gemini_key():
            sample = gemini_search_ranking(q, brand, host)
            found = sample["found"]
            pos = sample["position"]
            time.sleep(1)  # gentle rate limit between grounded searches
        else:
            sample = {"found": False, "position": None, "competitors": []}
            found = False
            pos = None
        if found and pos and pos <= 10:
            first_page_hits += 1
        score = 0
        if found and pos:
            if pos <= 3:
                score = clamp_score(100 - (pos - 1) * 12)
            elif pos <= 10:
                score = clamp_score(70 - (pos - 4) * 5)
            elif pos <= 20:
                score = clamp_score(30 - (pos - 11) * 2)
        note = "Measured: site host was not in the web-search sample."
        if found and pos:
            note = f"About position {pos}" if pos <= 10 else f"Found on page 2 (position {pos})"
        elif not gemini_key():
            note = "Search sample skipped — gemini_api not configured."
        for ch in sample.get("competitors") or []:
            competitors[ch] = f"https://{ch}"
        search_obs.append({"query": q, "score": score, "position": pos, "found": found, "note": note})

    # Gemini AI answer sample (buyer prompts)
    ai_prompts = build_ai_prompts(brand, host, queries)
    gemini_mentions = 0
    gemini_citations = 0
    ai_competitors: list[str] = []
    for i, prompt in enumerate(ai_prompts):
        use_search = i >= 2  # category prompts use grounding
        resp = gemini_ask(prompt, use_search=use_search)
        text = resp.get("text") or ""
        if brand_mentioned(text, brand, host):
            gemini_mentions += 1
        if owned_citations(text, host) or any(
            site_host(u) == host for u in resp.get("grounding_urls") or []
        ):
            gemini_citations += 1
        if not brand_mentioned(text, brand, host):
            for word in re.findall(r"\b[A-Z][a-zA-Z+&\s]{2,40}\b", text):
                w = word.strip()
                if w.lower() not in brand.lower() and len(w) > 3:
                    ai_competitors.append(w)
        time.sleep(0.5)

    # Places / listings (+ optional geocode check)
    places = places_lookup(brand, final_url)
    geocoded = geocode_address(places.get("address", "")) if places.get("ok") else {"ok": False}
    listings_score = 0
    if places.get("ok"):
        listings_score = 50
        if places.get("website") and host in site_host(places["website"]):
            listings_score += 25
        if places.get("rating"):
            listings_score += 15
        if places.get("review_count"):
            listings_score += 10
    listings_score = clamp_score(listings_score)

    # Component scores
    search_score = score_from_ratio(first_page_hits, len(queries))
    ai_score = score_from_ratio(gemini_mentions, len(ai_prompts))

    content_pts = 0
    if title:
        content_pts += 20
    if meta_desc:
        content_pts += 20
    if parser.h1_count == 1:
        content_pts += 20
    imgs = parser.images[:20]
    if imgs and sum(1 for i in imgs if (i.get("alt") or "").strip()) >= len(imgs) // 2:
        content_pts += 20
    if meta_content(parser, name="viewport"):
        content_pts += 20
    content_score = clamp_score(content_pts)

    structure_pts = 0
    if not robots_blocked and robots_text:
        structure_pts += 25
    if sitemap_url:
        structure_pts += 25
    if canonical:
        structure_pts += 20
    if schema:
        structure_pts += 15
    if "LocalBusiness" in schema or "Organization" in schema:
        structure_pts += 15
    structure_score = clamp_score(structure_pts)

    health_pts = 0
    if ps_home_m.get("ok"):
        perf = ps_home_m.get("performance") or 0
        health_pts += int(perf * 0.6)
        lcp_ms = ps_home_m.get("lcp_ms")
        if lcp_ms is not None:
            if lcp_ms <= 2500:
                health_pts += 20
            elif lcp_ms <= 4000:
                health_pts += 10
        cls_num = ps_home_m.get("cls_num")
        if cls_num is not None:
            if cls_num <= 0.1:
                health_pts += 20
            elif cls_num <= 0.25:
                health_pts += 10
    elif reachable:
        health_pts = 40
    site_health_score = clamp_score(health_pts)

    overall = clamp_score(
        search_score * 0.25
        + listings_score * 0.15
        + ai_score * 0.15
        + site_health_score * 0.2
        + content_score * 0.125
        + structure_score * 0.125
    )

    # Opportunity summary
    gaps: list[str] = []
    if search_score < 40:
        gaps.append("category buyers are not seeing you in web search samples")
    if ai_score < 40:
        gaps.append("AI answer engines name other firms on generic questions")
    if site_health_score < 60:
        gaps.append("mobile site speed needs work before traffic converts")
    if not gsc_configured():
        gaps.append("Search Console is not connected — ranks are Gemini search samples only")
    if gaps:
        opportunity = "Clear opportunity. " + " ".join(g.capitalize() + "." for g in gaps[:2])
    elif overall >= 70:
        opportunity = "Solid foundation. Focus on category visibility and ongoing measurement."
    else:
        opportunity = "Mixed visibility. Branded discovery works; category searches need attention."

    # At a glance metrics
    at_a_glance: list[dict] = []
    if ps_home_m.get("ok"):
        lcp_ms = ps_home_m.get("lcp_ms")
        at_a_glance.append(
            {
                "label": "Mobile LCP (homepage)",
                "value": ps_home_m.get("lcp") or "—",
                "status": metric_status("lower_is_better", lcp_ms, good=2500, warn=4000),
                "note": "PageSpeed Insights lab, mobile. Good is 2.5 s or faster.",
            }
        )
        cls_num = ps_home_m.get("cls_num")
        at_a_glance.append(
            {
                "label": "Mobile CLS (homepage)",
                "value": ps_home_m.get("cls") or "—",
                "status": metric_status("lower_is_better", cls_num, good=0.1, warn=0.25),
                "note": "PageSpeed Insights lab, mobile.",
            }
        )
        at_a_glance.append(
            {
                "label": "Mobile performance score (homepage)",
                "value": f"{ps_home_m.get('performance', '—')} / 100",
                "status": metric_status(
                    "higher_is_better", ps_home_m.get("performance"), good=90, warn=60
                ),
                "note": (
                    f"Desktop homepage scored {ps_home_d.get('performance', '—')} "
                    f"with {ps_home_d.get('lcp', '—')} LCP."
                    if ps_home_d.get("ok")
                    else "Desktop PageSpeed not available."
                ),
            }
        )
    for extra in ps_extra:
        if extra.get("ok"):
            at_a_glance.append(
                {
                    "label": f"Mobile LCP ({urlparse(extra['url']).path or 'page'})",
                    "value": extra.get("lcp") or "—",
                    "status": metric_status(
                        "lower_is_better", extra.get("lcp_ms"), good=2500, warn=4000
                    ),
                    "note": extra["url"],
                }
            )
    at_a_glance.append(
        {
            "label": "URLs in sitemap",
            "value": str(sitemap_count) if sitemap_count else "Not found",
            "status": "On track" if sitemap_count >= 5 else ("Watch" if sitemap_count else "Fix"),
            "note": f"Sitemap at {sitemap_url}" if sitemap_url else "No XML sitemap discovered.",
        }
    )
    at_a_glance.append(
        {
            "label": f"First-page presence ({len(queries)}-query sample)",
            "value": f"{first_page_hits} of {len(queries)}",
            "status": metric_status("higher_is_better", first_page_hits, good=7, warn=3),
            "note": f"Web-search sample via {search_method}. Not Search Console ranks.",
        }
    )
    at_a_glance.append(
        {
            "label": "Gemini mentions (sampled prompts)",
            "value": f"{gemini_mentions} of {len(ai_prompts)}",
            "status": metric_status("higher_is_better", gemini_mentions, good=7, warn=3),
            "note": "Branded vs category buyer prompts via Gemini (category prompts use Google Search grounding).",
        }
    )
    at_a_glance.append(
        {
            "label": "Gemini citations (sampled prompts)",
            "value": f"{gemini_citations} of {len(ai_prompts)}",
            "status": metric_status("higher_is_better", gemini_citations, good=7, warn=3),
            "note": "Owned URLs appeared as Gemini grounding sources.",
        }
    )

    other_facts: list[dict] = []
    https_ok = urlparse(final_url).scheme == "https" if reachable else False
    other_facts.append(
        {
            "label": "Homepage HTTPS",
            "status": "On track" if https_ok else "Fix",
            "detail": "HTTPS" if https_ok else "Site not confirmed on HTTPS",
        }
    )
    other_facts.append(
        {
            "label": "Homepage indexability",
            "status": "Fix" if robots_blocked else "On track",
            "detail": "robots.txt blocks all crawlers" if robots_blocked else "robots.txt allows indexing",
        }
    )
    if places.get("ok"):
        rc = places.get("review_count")
        rt = places.get("rating")
        other_facts.append(
            {
                "label": "Google Business Profile",
                "status": "On track" if rc else "Watch",
                "detail": (
                    f"{rt} from {rc} reviews — {places.get('name')}"
                    if rt and rc
                    else places.get("name") or "Listing found"
                ),
            }
        )
        if geocoded.get("ok"):
            other_facts.append(
                {
                    "label": "Listing address (Geocoding)",
                    "status": "On track",
                    "detail": geocoded.get("formatted") or places.get("address") or "",
                }
            )
    if not gsc_configured():
        other_facts.append(
            {
                "label": "Search Console",
                "status": "Watch",
                "detail": "Not connected — connect for true Google position history.",
            }
        )
    if not ga_configured():
        other_facts.append(
            {
                "label": "Google Analytics",
                "status": "Watch",
                "detail": "Not connected — traffic trends unavailable in this snapshot.",
            }
        )

    # Offers from headings
    offers: list[dict] = []
    for tag, text in parser.headings:
        if tag in ("h2", "h3") and text and len(text) < 100:
            offers.append({"name": text, "kind": "Service", "score": None})

    # Improvements
    improvements: list[dict] = []
    if search_score < 50:
        missed = [o["query"] for o in search_obs if not o["found"]]
        improvements.append(
            {
                "category": "Getting found",
                "priority": "Do this first",
                "title": f"{brand} does not appear for many service searches",
                "finding": (
                    f"In a {len(queries)}-query web-search sample, {host} appeared on "
                    f"{first_page_hits} first-page queries. "
                    f"Missed queries include: {', '.join(missed[:5])}."
                ),
                "recommendation": (
                    "Publish comparison-ready pages and third-party mentions for each offer. "
                    "Connect Search Console when ready for true Google positions."
                ),
                "pages": [final_url],
            }
        )
    if ai_score < 50:
        improvements.append(
            {
                "category": "Getting found",
                "priority": "Do this first",
                "title": "Gemini recommends other providers for category questions",
                "finding": (
                    f"Gemini named {brand} on {gemini_mentions} of {len(ai_prompts)} sampled prompts. "
                    f"Citations on owned URLs: {gemini_citations}."
                ),
                "recommendation": (
                    "Get listed on independent roundups and publish proof-backed service pages "
                    "that answer buyer questions in your category."
                ),
                "pages": [final_url],
            }
        )
    if ps_home_m.get("ok") and (ps_home_m.get("lcp_ms") or 0) > 2500:
        improvements.append(
            {
                "category": "Site health",
                "priority": "Do this first",
                "title": "Homepage is slow on mobile",
                "finding": (
                    f"Mobile LCP measured {ps_home_m.get('lcp')} on {final_url}. "
                    "Good is 2.5 seconds or faster."
                ),
                "recommendation": (
                    "Reduce hero weight, serve a correctly sized LCP image, and defer non-critical JavaScript."
                ),
                "pages": [final_url],
            }
        )
    if parser.h1_count != 1:
        improvements.append(
            {
                "category": "Your message",
                "priority": "Worth fixing",
                "title": "Homepage heading structure needs cleanup",
                "finding": f"Found {parser.h1_count} H1 headings; one clear H1 is preferred.",
                "recommendation": "Use one H1 that names the primary offer; keep supporting topics in H2/H3.",
                "pages": [final_url],
            }
        )
    if not sitemap_url:
        improvements.append(
            {
                "category": "Organization",
                "priority": "Worth fixing",
                "title": "No XML sitemap discovered",
                "finding": "Crawlers rely on sitemaps to discover new and updated pages.",
                "recommendation": "Publish sitemap.xml and reference it in robots.txt.",
                "pages": [base + "/robots.txt"],
            }
        )

    # Next steps
    next_steps: list[dict] = []
    for idx, imp in enumerate(improvements[:8], 1):
        effort = "Moderate" if imp["priority"] == "Do this first" else "Quick"
        next_steps.append(
            {
                "rank": idx,
                "badge": "Start here" if idx <= 3 else ("Then" if idx <= 6 else "Later"),
                "effort": effort,
                "title": imp["title"],
                "detail": imp["recommendation"],
            }
        )
    if not next_steps:
        next_steps.append(
            {
                "rank": 1,
                "badge": "Start here",
                "effort": "Quick",
                "title": "Maintain current visibility",
                "detail": "Keep NAP, sitemap, and content updated; re-run this snapshot weekly.",
            }
        )

    comp_rows = []
    seen = set()
    for ch, link in list(competitors.items())[:10]:
        if ch in seen:
            continue
        seen.add(ch)
        comp_rows.append({"name": ch.split(".")[0].title(), "site": ch, "link": link, "notes": "Observed in search sample."})
    for name in ai_competitors[:5]:
        if name.lower() not in seen:
            comp_rows.append({"name": name, "site": "", "link": "", "notes": "Named in Gemini sample."})

    return {
        "site_url": site_url,
        "final_url": final_url,
        "host": host,
        "brand": brand,
        "reachable": reachable,
        "opportunity": opportunity,
        "overall_score": overall,
        "scores": {
            "search": search_score,
            "listings": listings_score,
            "ai_answers": ai_score,
            "site_health": site_health_score,
            "content": content_score,
            "structure": structure_score,
        },
        "at_a_glance": at_a_glance,
        "other_facts": other_facts,
        "offers": offers[:12],
        "search_observations": search_obs,
        "improvements": improvements,
        "competitors": comp_rows[:10],
        "next_steps": next_steps,
        "homepage": {
            "ok": homepage["ok"],
            "status": homepage["status"],
            "elapsed_ms": homepage["elapsed_ms"],
            "error": homepage["error"],
        },
        "title": title,
        "meta_desc": meta_desc,
        "api_notes": {
            "gsc": gsc_configured(),
            "ga": ga_configured(),
            "pagespeed": bool(google_key("PAGESPEED")),
            "gemini": bool(gemini_key()),
            "places": bool(google_key("PLACES")),
            "geocoding": bool(google_key("GEOCODING")),
            "search_method": search_method,
        },
    }


# ---------------------------------------------------------------------------
# HTML report (Oasbit visibility template)
# ---------------------------------------------------------------------------


def esc(s: Any) -> str:
    return htmlmod.escape("" if s is None else str(s), quote=True)


def status_color(status: str) -> str:
    return {"On track": "#059669", "Watch": "#D97706", "Fix": "#DC2626"}.get(status, "#64748B")


# ---------------------------------------------------------------------------
# NOTE on inline styling constraints
# ---------------------------------------------------------------------------
# The Admin → Reports RICH_TEXT renderer sanitizes inline `style` attributes
# down to a narrow allowlist before it ever reaches the client portal. Verified
# by inspecting the rendered DOM of a published report:
#   survives : color, background (solid hex only — gradients/rgba are
#              dropped), font-family, font-size, font-weight, line-height,
#              letter-spacing, text-align, width, height, min-width,
#              max-width, padding (shorthand), border (shorthand, all sides),
#              border-radius, border-collapse
#   stripped : margin (all variants), display (no flex/grid/inline-block),
#              text-transform, list-style, float, single-side borders
#              (border-left/right/top/bottom), background-image/gradient
# Every helper below is written to stay inside the surviving set only:
#  - vertical spacing uses explicit spacer() divs, never margin
#  - multi-column layout uses <table> (rows/cols survive display:flex loss)
#  - "uppercase" labels are written as literal uppercase text, not CSS
#  - accent bars use a colored table cell instead of border-left
#  - table row separators use full `border` + zebra background instead of
#    border-bottom


def spacer(px: int) -> str:
    return f'<div style="height:{px}px;"></div>'


def score_tier_color(score: int) -> str:
    return "#059669" if score >= 70 else ("#D97706" if score >= 40 else "#DC2626")


def score_card(label: str, score: int, desc: str) -> str:
    color = score_tier_color(score)
    return f"""<table style="width:100%;border-collapse:collapse;">
<tr>
<td style="padding:0;color:#F1F5F9;font-size:14px;font-weight:700;">{esc(label)}</td>
<td style="padding:0;color:{color};font-size:22px;font-weight:800;text-align:right;">{score}</td>
</tr>
</table>
{spacer(6)}
<p style="padding:0;font-size:12px;color:#94A3B8;line-height:1.45;">{esc(desc)}</p>
{spacer(10)}
<div style="height:8px;background:#1E293B;border-radius:6px;">
<div style="height:8px;width:{score}%;background:{color};border-radius:6px;"></div>
</div>
{spacer(6)}
<p style="padding:0;font-size:11px;color:#64748B;letter-spacing:0.06em;">SCORE OUT OF 100</p>"""


def score_cards_row(cards: list[tuple[str, int, str]]) -> str:
    tds = "".join(
        f'<td style="width:{100 // len(cards)}%;padding:14px;">{score_card(l, s, d)}</td>'
        for l, s, d in cards
    )
    return f'<table style="width:100%;border-collapse:collapse;"><tr>{tds}</tr></table>'


def overall_badge(overall: int) -> str:
    color = score_tier_color(overall)
    size = 168
    return f"""<div style="width:{size}px;height:{size}px;border:10px solid {color};border-radius:999px;background:#0B1220;text-align:center;line-height:{size}px;">
<span style="font-size:40px;font-weight:800;color:#F8FAFC;">{overall}</span><span style="font-size:15px;color:#94A3B8;">/100</span>
</div>
{spacer(10)}
<p style="text-align:center;font-size:12px;color:#94A3B8;letter-spacing:0.06em;">OVERALL</p>"""


def scores_section(scores: dict, overall: int) -> str:
    channel_cards = score_cards_row(
        [
            ("Search", scores.get("search", 0), "Whether search engines can find and rank your pages for the work you sell."),
            ("Listings", scores.get("listings", 0), "Google Business Profile, map pin, and name-address-phone consistency."),
            ("AI answers", scores.get("ai_answers", 0), "Whether Gemini names or cites you on buyer questions in your category."),
        ]
    )
    website_cards = score_cards_row(
        [
            ("Site health", scores.get("site_health", 0), "Page speed, HTTPS, and whether key URLs load cleanly on mobile."),
            ("Content", scores.get("content", 0), "Unique copy, meta tags, headings, and proof on key pages."),
            ("Structure", scores.get("structure", 0), "Sitemaps, canonicals, schema, and information architecture."),
        ]
    )
    return f"""<div style="background:#0B1220;border:1px solid #1E293B;border-radius:16px;padding:24px;">
<table style="width:100%;border-collapse:collapse;">
<tr>
<td style="width:200px;padding:0 20px 0 0;">{overall_badge(overall)}</td>
<td style="padding:0;">
<p style="padding:0 0 10px;font-size:12px;color:#64748B;letter-spacing:0.08em;">CHANNELS</p>
{channel_cards}
</td>
</tr>
</table>
{spacer(18)}
<p style="padding:0 0 10px;font-size:12px;color:#64748B;letter-spacing:0.08em;">WEBSITE</p>
{website_cards}
</div>"""


def build_html(client_name: str, business: str, audit: dict) -> str:
    brand = audit.get("brand") or business or client_name
    host = audit.get("host") or site_host(audit["site_url"])
    site = audit["site_url"]
    overall = audit["overall_score"]
    scores = audit["scores"]
    prepared = TODAY.strftime("%b %d, %Y")

    glance_cards = ""
    glance = audit.get("at_a_glance") or []
    for i in range(0, len(glance), 2):
        pair = glance[i : i + 2]
        cells = ""
        for m in pair:
            st = m.get("status") or "Watch"
            cells += f"""<td style="width:50%;padding:8px;">
<div style="padding:14px 16px;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;">
<p style="padding:0 0 4px;font-size:13px;color:#64748B;">{esc(m.get('label'))}</p>
<p style="padding:0 0 6px;font-size:22px;font-weight:700;color:#0F172A;">{esc(m.get('value'))}</p>
<span style="padding:3px 10px;font-size:11px;font-weight:700;border-radius:999px;color:#FFF;background:{status_color(st)};">{esc(st)}</span>
<p style="padding:8px 0 0;font-size:12px;color:#64748B;line-height:1.4;">{esc(m.get('note'))}</p>
</div>
</td>"""
        if len(pair) == 1:
            cells += '<td style="width:50%;padding:8px;"></td>'
        glance_cards += f'<table style="width:100%;border-collapse:collapse;"><tr>{cells}</tr></table>'

    facts = ""
    other_facts = audit.get("other_facts") or []
    for i, f in enumerate(other_facts):
        st = f.get("status") or "Watch"
        facts += f"""<div style="padding:12px 14px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">
<strong style="color:#0F172A;">{esc(f.get('label'))}</strong>
<span style="padding:2px 8px;font-size:11px;font-weight:700;border-radius:999px;color:#FFF;background:{status_color(st)};">{esc(st)}</span>
<p style="padding:6px 0 0;font-size:13px;color:#475569;">{esc(f.get('detail'))}</p>
</div>"""
        if i < len(other_facts) - 1:
            facts += spacer(10)

    offers = ""
    offer_list = audit.get("offers") or []
    for i, o in enumerate(offer_list):
        sc = o.get("score")
        sc_cell = f'<span style="color:#94A3B8;">{sc}</span>' if sc is not None else ""
        offers += f"""<table style="width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;">
<tr>
<td style="padding:10px 12px;"><strong style="color:#0F172A;">{esc(o.get('name'))}</strong> {sc_cell}</td>
<td style="padding:10px 12px;text-align:right;font-size:12px;color:#64748B;">{esc(o.get('kind'))}</td>
</tr>
</table>"""
        if i < len(offer_list) - 1:
            offers += spacer(8)

    search_rows = ""
    for idx, o in enumerate(audit.get("search_observations") or [], 1):
        sc = o.get("score") or 0
        bg = "#FFFFFF" if idx % 2 else "#F8FAFC"
        search_rows += f"""<tr style="background:{bg};">
<td style="padding:10px 12px;color:#64748B;font-size:13px;">{idx:02d}</td>
<td style="padding:10px 12px;color:#0F172A;font-weight:600;">{esc(o.get('query'))}</td>
<td style="padding:10px 12px;color:#0F172A;font-weight:700;">{sc}</td>
<td style="padding:10px 12px;color:#475569;font-size:13px;">{esc(o.get('note'))}</td>
</tr>"""

    improve_blocks = ""
    improvements = audit.get("improvements") or []
    for i, imp in enumerate(improvements):
        pages = "".join(
            f'<p style="padding:0 0 4px;font-size:13px;"><a href="{esc(p)}" style="color:#2563EB;">{esc(p)}</a></p>'
            for p in imp.get("pages") or []
        )
        category_line = f"{esc(imp.get('category', '')).upper()} · {esc(imp.get('priority', '')).upper()}"
        improve_blocks += f"""<table style="width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;">
<tr>
<td style="width:4px;padding:0;background:#2563EB;"></td>
<td style="padding:16px 18px;">
<p style="padding:0 0 4px;font-size:11px;font-weight:700;letter-spacing:0.06em;color:#2563EB;">{category_line}</p>
<h3 style="padding:0 0 8px;font-size:16px;color:#0F172A;">{esc(imp.get('title'))}</h3>
<p style="padding:0 0 10px;font-size:14px;color:#475569;line-height:1.5;">{esc(imp.get('finding'))}</p>
<p style="padding:0 0 6px;font-size:12px;font-weight:700;color:#0F172A;letter-spacing:0.04em;">WHAT WE RECOMMEND</p>
<p style="padding:0 0 10px;font-size:14px;color:#334155;line-height:1.5;">{esc(imp.get('recommendation'))}</p>
{pages}
</td>
</tr>
</table>"""
        if i < len(improvements) - 1:
            improve_blocks += spacer(14)

    comp_rows = ""
    for idx, c in enumerate(audit.get("competitors") or [], 1):
        link = c.get("link") or (f"https://{c['site']}" if c.get("site") else "")
        name_cell = (
            f'<a href="{esc(link)}" style="color:#2563EB;">{esc(c.get("name"))}</a>'
            if link
            else esc(c.get("name"))
        )
        bg = "#FFFFFF" if idx % 2 else "#F8FAFC"
        comp_rows += f"""<tr style="background:{bg};">
<td style="padding:10px 12px;">{idx:02d}</td>
<td style="padding:10px 12px;">{name_cell}</td>
<td style="padding:10px 12px;color:#475569;">{esc(c.get('site'))}</td>
<td style="padding:10px 12px;color:#64748B;font-size:13px;">{esc(c.get('notes'))}</td>
</tr>"""

    steps = ""
    next_steps = audit.get("next_steps") or []
    for i, s in enumerate(next_steps):
        steps += f"""<table style="width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;">
<tr>
<td style="width:40px;padding:14px 0 14px 16px;font-size:18px;font-weight:700;color:#94A3B8;">{s.get('rank', 0):02d}</td>
<td style="padding:14px 16px;">
<p style="padding:0 0 4px;font-size:11px;font-weight:700;color:#2563EB;">{esc(s.get('badge'))} · {esc(s.get('effort'))}</p>
<h3 style="padding:0 0 6px;font-size:15px;color:#0F172A;">{esc(s.get('title'))}</h3>
<p style="padding:0;font-size:13px;color:#475569;line-height:1.45;">{esc(s.get('detail'))}</p>
</td>
</tr>
</table>"""
        if i < len(next_steps) - 1:
            steps += spacer(12)

    unreachable = ""
    if not audit.get("reachable"):
        unreachable = f"""<div style="padding:12px 14px;background:#FEE2E2;color:#991B1B;border:1px solid #FECACA;border-radius:8px;">
<strong>Site unreachable.</strong> Could not fully load {esc(site)}. Scores reflect partial data.</div>
{spacer(16)}"""

    section_pad = "padding:0 28px;"
    h2 = "padding:0 0 14px;font-size:18px;font-weight:700;color:#0F172A;"

    return f"""<div style="padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#0F172A;background:#F1F5F9;line-height:1.5;">
<div style="background:#0B1220;color:#FFFFFF;padding:32px 28px 28px;">
<p style="padding:0 0 6px;font-size:12px;letter-spacing:0.1em;color:#93C5FD;">PRIVATE AI AND SEARCH SNAPSHOT · CONNECTION INC</p>
<h1 style="padding:0 0 10px;font-size:28px;line-height:1.2;color:#FFFFFF;">How visible is {esc(brand)}?</h1>
<p style="padding:0 0 16px;font-size:15px;color:#CBD5E1;max-width:720px;line-height:1.55;">{esc(audit.get('opportunity'))}</p>
<p style="padding:0;font-size:13px;color:#94A3B8;">Prepared on {esc(prepared)} · Website <a href="{esc(site)}" style="color:#93C5FD;">{esc(host)}</a></p>
</div>
<div style="height:4px;background:#2563EB;"></div>
{spacer(24)}
<div style="{section_pad}">
{unreachable}
<h2 style="{h2}">Scores</h2>
<p style="padding:0 0 16px;font-size:13px;color:#64748B;">Channels are how people discover you. Site scores are how ready the website is when they arrive.</p>
{scores_section(scores, overall)}
</div>
{spacer(28)}
<div style="{section_pad}">
<h2 style="{h2}">Facts · At a glance</h2>
{glance_cards}
{spacer(6)}
<h3 style="padding:16px 0 10px;font-size:14px;font-weight:700;color:#64748B;">Other facts</h3>
{facts}
</div>
{spacer(28)}
<div style="{section_pad}">
<h2 style="{h2}">Offers · What you offer</h2>
<p style="padding:0 0 12px;font-size:13px;color:#64748B;">Services and products found on the live site.</p>
{offers or '<p style="color:#64748B;">No service headings detected on the homepage.</p>'}
</div>
{spacer(28)}
<div style="{section_pad}">
<h2 style="{h2}">Search · Where you show up</h2>
<p style="padding:0 0 12px;font-size:13px;color:#64748B;">Search observations from this snapshot — sample ranks, not Search Console history.</p>
<table style="width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;font-size:14px;">
<thead><tr style="background:#F1F5F9;">
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">#</th>
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">Query</th>
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">Score</th>
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">Note</th>
</tr></thead>
<tbody>{search_rows}</tbody>
</table>
</div>
{spacer(28)}
<div style="{section_pad}">
<h2 style="{h2}">Improve · What to improve</h2>
{improve_blocks or '<p style="color:#64748B;">No critical improvements flagged this week.</p>'}
</div>
{spacer(28)}
<div style="{section_pad}">
<h2 style="{h2}">Compare · How you compare</h2>
<p style="padding:0 0 12px;font-size:13px;color:#64748B;">Firms observed in the same sampled searches and AI answers.</p>
<table style="width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;font-size:14px;">
<thead><tr style="background:#F1F5F9;">
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">#</th>
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">Company</th>
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">Site</th>
<th style="padding:10px 12px;text-align:left;color:#64748B;font-size:12px;">Notes</th>
</tr></thead>
<tbody>{comp_rows or '<tr><td colspan="4" style="padding:12px;color:#64748B;">No competitors observed in this sample.</td></tr>'}</tbody>
</table>
</div>
{spacer(28)}
<div style="{section_pad}">
<h2 style="{h2}">Next · Your next steps</h2>
<p style="padding:0 0 14px;font-size:13px;color:#64748B;">Work from the top for the fastest lift.</p>
{steps}
</div>
{spacer(20)}
<div style="border:1px solid #E2E8F0;background:#FFFFFF;padding:16px 28px;">
<p style="padding:0;font-size:12px;color:#64748B;line-height:1.5;">Private AI and search snapshot for {esc(client_name)}. Generated {esc(REPORT_DATE)} by Connection Inc weekly automation. Search observations use Gemini with Google Search grounding — sample-based, not guaranteed Google positions. Connect Search Console and Analytics for historical data.</p>
</div>
</div>"""


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def publish(client: dict, audit: dict) -> dict:
    cid = client["id"]
    name = client["name"]
    site = audit["site_url"]
    title = f"Weekly Visibility Report — {name} — {REPORT_DATE}"
    description = f"Visibility snapshot for {site} (week of {WEEK_OF})."
    html = build_html(name, client.get("businessName") or name, audit)
    payload = {
        "title": title,
        "reportSource": "RICH_TEXT",
        "content": html,
        "status": "DRAFT",
        "clientPortalEnabled": True,
        "description": description,
        "clientId": cid,
        "clientIds": [cid],
    }
    status, created = api_send("POST", "/reports", payload)
    result = {
        "client": name,
        "clientId": cid,
        "site": site,
        "createStatus": status,
        "reportId": None,
        "htmlStored": False,
        "htmlChars": len(html),
        "portalEnabled": False,
        "assignmentLanded": False,
        "assignmentNote": "",
        "overallScore": audit.get("overall_score"),
        "reachable": audit.get("reachable"),
        "apiNotes": audit.get("api_notes"),
    }
    if status not in (200, 201) or not isinstance(created, dict) or not created.get("id"):
        result["assignmentNote"] = f"POST /reports failed HTTP {status}"
        return result
    rid = created["id"]
    result["reportId"] = rid
    stored = created.get("content") or ""
    result["htmlStored"] = bool(stored) and "<div" in stored
    result["portalEnabled"] = bool(created.get("clientPortalEnabled"))

    pstatus, patched = api_send(
        "PATCH",
        f"/reports/{rid}",
        {
            "clientPortalEnabled": True,
            "assignedClients": [cid],
            "assignmentNotes": f"Weekly visibility snapshot for {name}.",
        },
    )
    if pstatus in (200, 201) and isinstance(patched, dict):
        result["portalEnabled"] = bool(patched.get("clientPortalEnabled", True))
        if patched.get("content"):
            result["htmlStored"] = "<div" in patched["content"]

    gstatus, got = api_get(f"/reports/{rid}/assignments")
    assignments = got if isinstance(got, list) else (got.get("assignments") or got.get("data") or [])
    active = [
        a
        for a in assignments
        if isinstance(a, dict) and a.get("clientId") == cid and not a.get("disassociatedAt")
    ]
    result["assignmentLanded"] = bool(active)
    result["assignmentNote"] = (
        f"Assigned (PATCH HTTP {pstatus}, GET HTTP {gstatus})."
        if active
        else f"Created; verify assignment in Admin → Reports (PATCH HTTP {pstatus})."
    )
    return result


def main() -> int:
    summaries = []
    for _label, cid in PILOTS:
        status, client = api_get(f"/clients/{cid}")
        if status != 200 or not isinstance(client, dict):
            summaries.append(
                {
                    "client": _label,
                    "clientId": cid,
                    "skipped": True,
                    "reason": f"GET /clients/{{id}} HTTP {status}",
                    "reportId": None,
                }
            )
            print(json.dumps(summaries[-1]))
            continue
        name = client.get("name") or _label
        if client.get("archivedAt"):
            summaries.append({"client": name, "clientId": cid, "skipped": True, "reason": "archived", "reportId": None})
            print(json.dumps(summaries[-1]))
            continue
        site = website_url_from_client(client)
        if not site:
            summaries.append(
                {
                    "client": name,
                    "clientId": cid,
                    "skipped": True,
                    "reason": "missing Credentials → Website URL",
                    "reportId": None,
                }
            )
            print(json.dumps(summaries[-1]))
            continue
        site = normalize_site_url(site)
        business = client.get("businessName") or name
        print(json.dumps({"event": "audit_start", "client": name, "site": site}))
        audit = audit_visibility(site, business)
        print(
            json.dumps(
                {
                    "event": "audit_done",
                    "client": name,
                    "reachable": audit["reachable"],
                    "overallScore": audit["overall_score"],
                    "scores": audit["scores"],
                    "apiNotes": audit["api_notes"],
                }
            )
        )
        pub = publish(client, audit)
        summaries.append(pub)
        print(json.dumps({k: v for k, v in pub.items()}))

    out_path = "/tmp/weekly_seo_results.json"
    with open(out_path, "w") as f:
        json.dump(summaries, f, indent=2)
    print(json.dumps({"event": "complete", "resultsPath": out_path, "count": len(summaries)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
