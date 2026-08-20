"""HTTP fetch, HTML parsing, robots.txt, and sitemap helpers."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import TIMEOUT, UA
from .portal import site_host

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

