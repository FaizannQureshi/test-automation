"""Discover sellable services/products for Offers and search queries."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from .env import gemini_key
from .portal import custom_field_value, site_host

def schema_offer_names(json_ld_blocks: list[str]) -> list[dict]:
    """Extract Service / Product / Offer names from JSON-LD."""
    offer_types = {
        "service",
        "product",
        "offer",
        "financialproduct",
        "loanorcredit",
        "professionalservice",
    }
    found: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not isinstance(node, dict):
            return
        types = node.get("@type")
        type_list = [types] if isinstance(types, str) else (types if isinstance(types, list) else [])
        type_norm = {str(t).lower() for t in type_list}
        if type_norm & offer_types:
            name = (node.get("name") or node.get("serviceType") or "").strip()
            if name and name.lower() not in seen and looks_like_offer_name(name):
                seen.add(name.lower())
                kind = "Product" if "product" in type_norm else "Service"
                found.append({"name": name, "kind": kind, "score": None, "source": "schema"})
        for v in node.values():
            if isinstance(v, (dict, list)):
                walk(v)

    for blob in json_ld_blocks:
        try:
            walk(json.loads(blob))
        except json.JSONDecodeError:
            continue
    return found


# Exact / whole-name marketing labels that are not sellable services
_OFFER_NOISE = re.compile(
    r"(?i)^("
    r"home|about|about us|contact|contact us|blog|news|faq|faqs|privacy|terms|"
    r"get started|learn more|read more|click here|welcome|our team|meet the team|"
    r"testimonials|reviews|resources|menu|navigation|footer|header|"
    r"let'?s talk.*|reach .*|serving .*|talk through.*|schedule .*|"
    r"book .*|call us|get in touch|why (choose|us|work)|how it works|"
    r"what (we|clients) say|ready to|start here|next steps?"
    r")$"
)

# Tools, chatbots, and content hubs — not products a buyer purchases
_OFFER_TOOL_NOISE = re.compile(
    r"(?i)\b("
    r"gpt|chatgpt|chat\s*bot|calculator|calc|planner|toolbox|utilities|"
    r"inspiration|checklist|cookie|privacy\s*policy|savebot|game\s*privacy"
    r")\b"
)

# Match only inside URL path (never the hostname — avoids "loan" in amydebuskhomeloans.com)
_SERVICE_PATH_HINTS = (
    "service",
    "services",
    "product",
    "products",
    "solution",
    "solutions",
    "mortgage",
    "loan",
    "loans",
    "lender",
    "refinance",
    "refinancing",
    "pre-approval",
    "preapproval",
    "heloc",
    "fha",
    "va-",
    "/va/",
    "conventional",
    "jumbo",
    "first-time",
    "first_time",
    "dscr",
    "reverse-mortgage",
    "down-payment",
    "self-employed",
    "bank-statement",
    "fix-and-flip",
    "private-money",
    "investment",
    "commercial",
    "remodel",
    "construction",
)

# Slug tokens that mean "not a sellable service page"
_PATH_NOISE_TOKENS = (
    "gpt",
    "calc",
    "calculator",
    "planner",
    "toolbox",
    "utilities",
    "inspiration",
    "checklist",
    "blog",
    "about",
    "contact",
    "privacy",
    "cookie",
    "resources",
    "citations",
    "trust-and",
    "savebot",
    "homebuyer-resources",
    "home-buyers-check",
    "free-home-value",
)


def looks_like_offer_name(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) < 3 or len(t) > 90:
        return False
    if _OFFER_NOISE.match(t):
        return False
    if _OFFER_TOOL_NOISE.search(t):
        return False
    if t.endswith("?") and not any(k in t.lower() for k in ("loan", "mortgage", "refinance")):
        return False
    words = t.split()
    if len(words) > 12:
        return False
    return True


def title_from_url_slug(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    slug = path.split("/")[-1]
    slug = re.sub(r"\.(html?|php)$", "", slug, flags=re.I)
    slug = slug.replace("-", " ").replace("_", " ").strip()
    return " ".join(w.capitalize() if w.islower() else w for w in slug.split())


def _path_has_service_hint(path: str) -> bool:
    """True if the URL path (not host) looks like a service/product page."""
    p = (path or "").lower()
    if not p or p in ("/", ""):
        return False
    if any(tok in p for tok in _PATH_NOISE_TOKENS):
        return False
    return any(h in p for h in _SERVICE_PATH_HINTS)


def _path_offer_priority(path: str) -> int:
    """Higher = better candidate for Offers list."""
    p = (path or "").lower()
    score = 0
    strong = (
        "first-time",
        "va-",
        "/va/",
        "fha",
        "refinance",
        "self-employed",
        "dscr",
        "reverse-mortgage",
        "down-payment",
        "bank-statement",
        "fix-and-flip",
        "private-money",
        "jumbo",
        "heloc",
        "conventional",
        "remodel",
        "construction",
        "mortgage-product",
    )
    for s in strong:
        if s in p:
            score += 10
    if "lender" in p or "loan" in p or "mortgage" in p:
        score += 3
    # Prefer shallow product URLs over deep blog-ish paths
    depth = len([x for x in p.split("/") if x])
    score -= max(0, depth - 1)
    return score


def offers_from_portal_client(client: dict | None) -> list[dict]:
    if not client:
        return []
    # Prefer explicit service lists — not raw SEO "Keywords" dumps
    raw = custom_field_value(
        client,
        "Services",
        "Service List",
        "Offers",
        "Products",
        "Service Keywords",
    )
    if not raw:
        return []
    parts = re.split(r"[\n,;|/]+", raw)
    out: list[dict] = []
    seen: set[str] = set()
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" -•*")
        if not looks_like_offer_name(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "kind": "Service", "score": None, "source": "portal"})
    return out[:12]


def offers_from_sitemap(page_urls: list[str], host: str) -> list[dict]:
    candidates: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for url in page_urls:
        if site_host(url) != host:
            continue
        path = urlparse(url).path.lower()
        if path in ("", "/"):
            continue
        if not _path_has_service_hint(path):
            continue
        name = title_from_url_slug(url)
        if not looks_like_offer_name(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            (
                _path_offer_priority(path),
                {"name": name, "kind": "Service", "score": None, "source": "sitemap", "url": url},
            )
        )
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:12]]


def offers_from_gemini(brand: str, host: str, homepage_html: str) -> list[dict]:
    if not gemini_key() or not homepage_html:
        return []
    from .google_apis import gemini_ask

    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", homepage_html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()[:3500]
    prompt = (
        f"Business: {brand} ({host}).\n"
        "From this homepage text, list ONLY sellable services or loan products a customer would buy "
        "(e.g. FHA loans, VA home loans, refinance, down payment assistance, self-employed loans).\n"
        "Do NOT list: marketing slogans, CTAs, locations, team bios, nav labels, GPT/chat tools, "
        "calculators, planners, blogs, or resource hubs.\n"
        "Reply with one service per line, plain text, max 10 lines. No numbering.\n\n"
        f"Homepage text:\n{text}"
    )
    resp = gemini_ask(prompt, use_search=False)
    raw = resp.get("text") or ""
    out: list[dict] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        name = re.sub(r"^[\d\.\-\*\•]+\s*", "", line).strip()
        name = name.strip("\"'`")
        if not looks_like_offer_name(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "kind": "Service", "score": None, "source": "gemini"})
    return out[:10]


def discover_offers(
    *,
    client: dict | None,
    brand: str,
    host: str,
    json_ld: list[str],
    page_urls: list[str],
    homepage_html: str,
) -> list[dict]:
    """Resolve real services/products — never treat marketing H2/H3 as offers."""
    portal = offers_from_portal_client(client)
    if portal:
        return portal[:12]

    schema = schema_offer_names(json_ld)
    sitemap = offers_from_sitemap(page_urls, host)

    merged: list[dict] = []
    seen: set[str] = set()
    for group in (schema, sitemap):
        for o in group:
            key = (o.get("name") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(o)

    # Prefer Gemini when sitemap/schema are thin or mostly weak matches
    if len(merged) < 6:
        for o in offers_from_gemini(brand, host, homepage_html):
            key = (o.get("name") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(o)

    return merged[:12]


def service_like_pages(page_urls: list[str], host: str, offers: list[dict] | None = None) -> list[str]:
    scored: list[tuple[int, str]] = []
    for url in page_urls:
        if site_host(url) != host:
            continue
        path = urlparse(url).path.lower()
        if not _path_has_service_hint(path):
            continue
        scored.append((_path_offer_priority(path), url))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked: list[str] = []
    for _, url in scored:
        if url not in picked:
            picked.append(url)
        if len(picked) >= 3:
            break
    if offers:
        for o in offers:
            u = o.get("url")
            if u and u not in picked:
                picked.append(u)
            if len(picked) >= 3:
                break
    return picked[:3]
