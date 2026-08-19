#!/usr/bin/env python3
"""Weekly Connection Inc client SEO snapshot. Never prints secrets."""

from __future__ import annotations

import html as htmlmod
import json
import os
import re
import ssl
import sys
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://seo.connectionincorporated.com/api/v1"
UA = (
    "Mozilla/5.0 (compatible; ConnectionIncWeeklySEO/1.0; "
    "+https://seo.connectionincorporated.com)"
)
TIMEOUT = 25
REPORT_DATE = "2026-08-19"
WEEK_OF = "2026-08-17"
# Single active pilot while report HTML contrast is verified in Admin → Reports.
PILOTS = [
    ("Adam Zeman", "cmkoitqae0001ib04j8hrefa9"),
]


def api_headers() -> dict[str, str]:
    key = os.environ.get("PORTAL_API_KEY") or ""
    if not key:
        raise SystemExit("PORTAL_API_KEY is not set")
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ConnectionInc-WeeklySEO/1.0",
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
    # Keep path; ensure we have a scheme/host
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )


def origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
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
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    adapter = HTTPAdapter(max_retries=Retry(total=0))
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def fetch(s: requests.Session, url: str, *, allow_redirects: bool = True) -> dict:
    started = time.monotonic()
    try:
        r = s.get(url, timeout=TIMEOUT, allow_redirects=allow_redirects, verify=True)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        history = [{"status": h.status_code, "url": h.headers.get("Location") or h.url} for h in r.history]
        return {
            "ok": True,
            "error": None,
            "status": r.status_code,
            "url": r.url,
            "elapsed_ms": elapsed_ms,
            "history": history,
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
            "history": [],
            "text": "",
            "headers": {},
            "content_type": "",
        }


def robots_blocks_all(text: str) -> bool:
    if not text:
        return False
    # Split into user-agent groups
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
    if not groups:
        # fallback: any Disallow: / line
        for ln in lines:
            if re.match(r"(?i)^disallow:\s*/\s*$", ln):
                return True
        return False
    for g in groups:
        agents = [a.lower() for a in g["agents"]]
        if "*" in agents or "googlebot" in agents:
            if "/" in g["disallows"] and not g["allows"]:
                return True
            if "/" in g["disallows"] and not any(a == "/" or a.startswith("/") for a in g["allows"]):
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
    return ("<urlset" in blob) or ("<sitemapindex" in blob) or ("<sitemap" in blob and "<?xml" in blob)


def finding(check: str, status: str, detail: str) -> dict:
    assert status in ("pass", "warn", "fail")
    return {"check": check, "status": status, "detail": detail}


def audit_site(site_url: str) -> dict:
    s = session()
    homepage = fetch(s, site_url)
    reachable = bool(homepage["ok"] and homepage["status"] and homepage["status"] < 400)
    findings: list[dict] = []
    parser = PageParser()
    title = ""
    meta_desc = ""
    canonical = ""
    viewport = ""
    og_title = ""
    if homepage["ok"] and homepage["text"]:
        try:
            parser.feed(homepage["text"])
        except Exception:
            pass
        title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
        meta_desc = meta_content(parser, name="description")
        canonical = canonical_href(parser)
        viewport = meta_content(parser, name="viewport")
        og_title = meta_content(parser, prop="og:title")

    # homepage status
    if not homepage["ok"]:
        findings.append(finding("Homepage status", "fail", f"Homepage could not be fetched ({homepage['error']})."))
    elif homepage["status"] and 200 <= homepage["status"] < 300:
        findings.append(finding("Homepage status", "pass", f"Final response HTTP {homepage['status']} in {homepage['elapsed_ms']} ms."))
    elif homepage["status"] and 300 <= homepage["status"] < 400:
        findings.append(finding("Homepage status", "warn", f"Ended on HTTP {homepage['status']} after redirects."))
    else:
        findings.append(finding("Homepage status", "fail", f"Final response HTTP {homepage['status']}."))

    # HTTPS
    final_url = homepage.get("url") or site_url
    if not homepage["ok"]:
        findings.append(finding("HTTPS", "fail", "Could not confirm HTTPS because the homepage was unreachable."))
    elif urlparse(final_url).scheme == "https":
        findings.append(finding("HTTPS", "pass", f"Served over HTTPS ({urlparse(final_url).netloc})."))
    else:
        findings.append(finding("HTTPS", "fail", f"Final URL is not HTTPS: {final_url}"))

    # HTTP → HTTPS redirect
    host = urlparse(site_url).netloc
    http_url = urlunparse(("http", host, "/", "", "", ""))
    http_fetch = fetch(s, http_url)
    if not http_fetch["ok"]:
        findings.append(
            finding(
                "HTTP to HTTPS redirect",
                "warn",
                f"Could not open {http_url} ({http_fetch['error']}). HTTPS homepage may still work.",
            )
        )
    elif urlparse(http_fetch["url"]).scheme == "https":
        findings.append(
            finding(
                "HTTP to HTTPS redirect",
                "pass",
                f"HTTP redirected to HTTPS ({http_fetch['url']}).",
            )
        )
    else:
        findings.append(
            finding(
                "HTTP to HTTPS redirect",
                "fail",
                f"HTTP request stayed on HTTP (final {http_fetch['url']}, status {http_fetch['status']}).",
            )
        )

    # title
    n = len(title)
    if not title:
        findings.append(finding("Title tag", "fail", "No title tag text found on the homepage."))
    elif 15 <= n <= 60:
        findings.append(finding("Title tag", "pass", f"{n} characters (target 15–60)."))
    else:
        findings.append(finding("Title tag", "warn", f"{n} characters (target 15–60). Current: “{title[:120]}”"))

    # meta description
    nd = len(meta_desc)
    if not meta_desc:
        findings.append(finding("Meta description", "fail", "No meta description found on the homepage."))
    elif 70 <= nd <= 160:
        findings.append(finding("Meta description", "pass", f"{nd} characters (target 70–160)."))
    else:
        findings.append(finding("Meta description", "warn", f"{nd} characters (target 70–160)."))

    # canonical
    if not canonical:
        findings.append(finding("Canonical", "fail", "No rel=canonical link on the homepage."))
    else:
        abs_can = urljoin(final_url, canonical)
        if urlparse(abs_can).scheme != "https":
            findings.append(finding("Canonical", "warn", f"Canonical is not HTTPS: {canonical}"))
        else:
            findings.append(finding("Canonical", "pass", f"Canonical present: {abs_can}"))

    # viewport
    if viewport:
        findings.append(finding("Viewport", "pass", f"Viewport meta present ({viewport[:80]})."))
    else:
        findings.append(finding("Viewport", "fail", "No viewport meta tag; mobile layout may be poor."))

    # og:title
    if og_title:
        findings.append(finding("Open Graph title", "pass", f"og:title present ({len(og_title)} characters)."))
    else:
        findings.append(finding("Open Graph title", "warn", "No og:title; social shares may fall back to the HTML title."))

    # H1
    if parser.h1_count == 1:
        h1_text = next((t for tag, t in parser.headings if tag == "h1"), "")
        findings.append(finding("H1 count", "pass", f"Exactly one H1 ({h1_text[:80] or 'text empty'})."))
    elif parser.h1_count == 0:
        findings.append(finding("H1 count", "fail", "No H1 heading on the homepage."))
    else:
        findings.append(finding("H1 count", "warn", f"{parser.h1_count} H1 headings; search engines prefer a single primary H1."))

    # image alt (up to 20)
    imgs = parser.images[:20]
    if not imgs:
        findings.append(finding("Image alt text", "pass", "No images in the first 20 to check."))
    else:
        missing = [img for img in imgs if not (img.get("alt") or "").strip()]
        if not missing:
            findings.append(finding("Image alt text", "pass", f"All {len(imgs)} checked images have alt text."))
        elif len(missing) == len(imgs):
            findings.append(finding("Image alt text", "fail", f"None of the {len(imgs)} checked images have alt text."))
        else:
            findings.append(
                finding(
                    "Image alt text",
                    "warn",
                    f"{len(missing)} of {len(imgs)} checked images are missing alt text.",
                )
            )

    # robots.txt
    robots_url = origin(final_url if homepage["ok"] else site_url) + "/robots.txt"
    robots = fetch(s, robots_url)
    robots_text = robots["text"] if robots["ok"] and robots["status"] == 200 else ""
    sitemap_candidates = sitemap_urls_from_robots(robots_text)
    if not robots["ok"] or robots["status"] != 200:
        findings.append(
            finding(
                "robots.txt",
                "warn",
                f"robots.txt not available (status {robots['status']}, {robots.get('error') or 'ok'}).",
            )
        )
        robots_disallow_all = False
    elif robots_blocks_all(robots_text):
        findings.append(finding("robots.txt", "fail", "robots.txt contains Disallow: / for a general crawler — the site may be blocked from indexing."))
        robots_disallow_all = True
    else:
        findings.append(finding("robots.txt", "pass", "robots.txt is present and does not Disallow: / for general crawlers."))
        robots_disallow_all = False

    # sitemap
    sitemap_found = None
    sitemap_fetch = None
    check_urls = list(sitemap_candidates)
    default_sitemap = origin(final_url if homepage["ok"] else site_url) + "/sitemap.xml"
    if default_sitemap not in check_urls:
        check_urls.append(default_sitemap)
    for su in check_urls:
        sitemap_fetch = fetch(s, su)
        if sitemap_fetch["ok"] and sitemap_fetch["status"] == 200 and looks_like_xml_sitemap(
            sitemap_fetch["text"], sitemap_fetch["content_type"]
        ):
            sitemap_found = sitemap_fetch["url"]
            break
    if sitemap_found:
        findings.append(finding("XML sitemap", "pass", f"XML sitemap found at {sitemap_found}."))
    else:
        extra = ""
        if sitemap_fetch:
            extra = f" Last attempt HTTP {sitemap_fetch.get('status')} at {sitemap_fetch.get('url')}."
        findings.append(finding("XML sitemap", "fail", "No XML sitemap found from robots.txt Sitemap: directives or /sitemap.xml." + extra))

    passed = sum(1 for f in findings if f["status"] == "pass")
    warns = sum(1 for f in findings if f["status"] == "warn")
    fails = sum(1 for f in findings if f["status"] == "fail")

    return {
        "site_url": site_url,
        "final_url": final_url,
        "reachable": reachable,
        "homepage": {
            "ok": homepage["ok"],
            "status": homepage["status"],
            "elapsed_ms": homepage["elapsed_ms"],
            "error": homepage["error"],
            "url": homepage["url"],
        },
        "title": title,
        "meta_desc": meta_desc,
        "canonical": canonical,
        "https": urlparse(final_url).scheme == "https" if homepage["ok"] else False,
        "robots_ok": bool(robots_text) and not robots_disallow_all,
        "robots_status": robots.get("status"),
        "sitemap": sitemap_found,
        "headings": parser.headings[:30],
        "findings": findings,
        "passed": passed,
        "warns": warns,
        "fails": fails,
        "http_redirect_final": http_fetch.get("url"),
    }


def esc(s: Any) -> str:
    return htmlmod.escape("" if s is None else str(s), quote=True)


def label_for(status: str) -> tuple[str, str, str]:
    if status == "pass":
        return "Pass", "#065F46", "#D1FAE5"
    if status == "warn":
        return "Needs work", "#92400E", "#FEF3C7"
    return "Fail", "#991B1B", "#FEE2E2"


def next_steps(audit: dict) -> list[str]:
    steps = []
    by = {f["check"]: f for f in audit["findings"]}
    order = [
        "Homepage status",
        "HTTPS",
        "HTTP to HTTPS redirect",
        "Title tag",
        "Meta description",
        "Canonical",
        "H1 count",
        "Image alt text",
        "robots.txt",
        "XML sitemap",
        "Viewport",
        "Open Graph title",
    ]
    for check in order:
        f = by.get(check)
        if not f or f["status"] == "pass":
            continue
        if check == "Homepage status":
            steps.append("Restore homepage availability (DNS, hosting, or firewall) so crawlers and customers can load the site.")
        elif check == "HTTPS":
            steps.append("Serve the live site on HTTPS with a valid certificate.")
        elif check == "HTTP to HTTPS redirect":
            steps.append("301-redirect all HTTP URLs to the matching HTTPS URL.")
        elif check == "Title tag":
            steps.append("Set a unique homepage title between 15 and 60 characters that names the business and primary service.")
        elif check == "Meta description":
            steps.append("Add a homepage meta description between 70 and 160 characters summarizing the offer.")
        elif check == "Canonical":
            steps.append("Add an absolute HTTPS rel=canonical on the homepage pointing at the preferred URL.")
        elif check == "H1 count":
            steps.append("Use a single clear H1 that matches the primary topic of the homepage.")
        elif check == "Image alt text":
            steps.append("Add descriptive alt text to homepage images so the content is understandable without the image.")
        elif check == "robots.txt":
            steps.append("Publish a robots.txt that allows indexing of public pages (avoid a sitewide Disallow: /).")
        elif check == "XML sitemap":
            steps.append("Publish an XML sitemap and reference it with a Sitemap: line in robots.txt.")
        elif check == "Viewport":
            steps.append("Add a viewport meta tag (for example width=device-width, initial-scale=1) for mobile usability.")
        elif check == "Open Graph title":
            steps.append("Add an og:title tag so shares on social networks show a proper headline.")
    if not steps:
        steps.append("Keep titles, canonicals, and the XML sitemap in sync when new pages go live.")
        steps.append("Re-check this snapshot after any homepage or CMS theme change.")
    return steps[:8]


# Portal report viewer paints table rows navy. Dark cell text is invisible.
# Put light text on every td/th and wrap copy in a span (same pattern as Pass pills).
CELL = "padding:10px 12px;vertical-align:top;color:#F8FAFC;background:#1E293B;border-bottom:1px solid #334155;"
TH_CELL = CELL + "font-weight:700;text-align:left;"
SPAN = "color:#F8FAFC;"


def cell_text(text: str, *, header: bool = False) -> str:
    st = TH_CELL if header else CELL
    tag = "th" if header else "td"
    return f'<{tag} style="{st}"><span style="{SPAN}">{text}</span></{tag}>'


def build_html(client_name: str, business: str, audit: dict) -> str:
    site = audit["site_url"]
    host = urlparse(site).netloc or site
    status_bit = (
        f"HTTP {audit['homepage']['status']} · {audit['homepage']['elapsed_ms']} ms"
        if audit["homepage"]["status"]
        else f"Unreachable · {audit['homepage']['elapsed_ms']} ms"
    )
    if audit["homepage"]["error"] and not audit["reachable"]:
        status_bit += f" · {audit['homepage']['error']}"

    def row(label: str, value: str) -> str:
        return f"<tr>{cell_text(esc(label), header=True)}{cell_text(value)}</tr>"

    finding_rows = []
    for f in audit["findings"]:
        lab, fg, bg = label_for(f["status"])
        pill = (
            f'<span style="display:inline-block;padding:4px 10px;font-size:12px;font-weight:700;'
            f'letter-spacing:0.02em;color:{fg};background:{bg};">{esc(lab)}</span>'
        )
        finding_rows.append(
            "<tr>"
            + cell_text(esc(f["check"]))
            + f'<td style="{CELL}">{pill}</td>'
            + cell_text(esc(f["detail"]))
            + "</tr>"
        )

    if audit["headings"]:
        heading_items = "".join(
            f'<li style="margin:0 0 6px;color:#0F172A;"><strong>{esc(tag.upper())}</strong> — {esc(text or "(empty)")}</li>'
            for tag, text in audit["headings"]
        )
        heading_block = f'<ul style="margin:0;padding-left:18px;">{heading_items}</ul>'
    else:
        heading_block = '<p style="margin:0;color:#0F172A;">No heading tags were detected on the homepage (or the page could not be parsed).</p>'

    steps = "".join(f'<li style="margin:0 0 8px;color:#0F172A;">{esc(x)}</li>' for x in next_steps(audit))
    title_disp = esc(audit["title"] or "(none)")
    meta_disp = esc(audit["meta_desc"] or "(none)")
    if len(audit["meta_desc"] or "") > 180:
        meta_disp = esc((audit["meta_desc"][:180] + "…"))
    can_disp = esc(audit["canonical"] or "(none)")
    https_disp = "Yes" if audit["https"] else "No"
    robots_disp = "Present" if audit["robots_ok"] else "Missing or blocking"
    sitemap_disp = esc(audit["sitemap"] or "Not found")
    url_html = (
        f'<a href="{esc(site)}" style="color:#93C5FD;text-decoration:underline;">'
        f'{esc(audit["final_url"] or site)}</a>'
    )

    unreachable_note = ""
    if not audit["reachable"]:
        unreachable_note = (
            '<p style="margin:0 0 16px;padding:12px 14px;background:#FEE2E2;color:#991B1B;border:1px solid #FECACA;">'
            f"<strong>Site unreachable.</strong> This snapshot could not load {esc(site)}. "
            "Findings below reflect that failed fetch; they are not a ranking score.</p>"
        )

    count_td = (
        "width:33%;padding:16px;vertical-align:top;color:#F8FAFC;background:#1E293B;"
        "border:1px solid #334155;"
    )

    return f"""<div style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#0F172A;background:#F8FAFC;line-height:1.5;">
<header>
<div style="background:#0F172A;color:#FFFFFF;padding:24px 28px;">
<p style="margin:0 0 8px;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#93C5FD;">Connection Inc · Weekly SEO report</p>
<h1 style="margin:0 0 8px;font-size:26px;line-height:1.25;color:#FFFFFF;">{esc(client_name)}</h1>
<p style="margin:0;font-size:15px;color:#CBD5E1;">{esc(business or client_name)}</p>
<p style="margin:12px 0 0;font-size:14px;color:#E2E8F0;">Week of {esc(WEEK_OF)} · <a href="{esc(site)}" style="color:#93C5FD;text-decoration:underline;">{esc(host)}</a></p>
</div>
</header>
<section>
<div style="padding:22px 28px 8px;">
{unreachable_note}
<table style="width:100%;border-collapse:separate;border-spacing:8px 0;">
<tr>
<td style="{count_td}">
<p style="margin:0;font-size:12px;color:#E2E8F0;text-transform:uppercase;letter-spacing:0.04em;"><span style="color:#E2E8F0;">Passed</span></p>
<p style="margin:4px 0 0;font-size:28px;font-weight:700;color:#6EE7B7;"><span style="color:#6EE7B7;">{audit['passed']}</span></p>
</td>
<td style="{count_td}">
<p style="margin:0;font-size:12px;color:#E2E8F0;text-transform:uppercase;letter-spacing:0.04em;"><span style="color:#E2E8F0;">Needs work</span></p>
<p style="margin:4px 0 0;font-size:28px;font-weight:700;color:#FCD34D;"><span style="color:#FCD34D;">{audit['warns']}</span></p>
</td>
<td style="{count_td}">
<p style="margin:0;font-size:12px;color:#E2E8F0;text-transform:uppercase;letter-spacing:0.04em;"><span style="color:#E2E8F0;">Failed</span></p>
<p style="margin:4px 0 0;font-size:28px;font-weight:700;color:#FCA5A5;"><span style="color:#FCA5A5;">{audit['fails']}</span></p>
</td>
</tr>
</table>
</div>
</section>
<section>
<div style="padding:8px 28px 16px;">
<h2 style="margin:0 0 12px;font-size:18px;color:#0F172A;">Site snapshot</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px;">
{row("Checked URL", url_html)}
{row("Status / time", esc(status_bit))}
{row("Title", title_disp)}
{row("Meta description", meta_disp)}
{row("Canonical", can_disp)}
{row("HTTPS", esc(https_disp))}
{row("robots.txt", esc(robots_disp))}
{row("XML sitemap", sitemap_disp)}
</table>
</div>
</section>
<section>
<div style="padding:8px 28px 16px;">
<h2 style="margin:0 0 12px;font-size:18px;color:#0F172A;">Heading outline</h2>
{heading_block}
</div>
</section>
<section>
<div style="padding:8px 28px 16px;">
<h2 style="margin:0 0 12px;font-size:18px;color:#0F172A;">Findings</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px;">
<tr>
{cell_text("Check", header=True)}
{cell_text("Result", header=True)}
{cell_text("Notes", header=True)}
</tr>
{''.join(finding_rows)}
</table>
<p style="margin:10px 0 0;font-size:13px;color:#0F172A;"><span style="color:#0F172A;"><strong>Pass</strong> = looks good. <strong>Needs work</strong> = improve when you can. <strong>Fail</strong> = fix first.</span></p>
</div>
</section>
<section>
<div style="padding:8px 28px 16px;">
<h2 style="margin:0 0 12px;font-size:18px;color:#0F172A;">Recommended next steps</h2>
<ol style="margin:0;padding-left:20px;">{steps}</ol>
</div>
</section>
<footer>
<div style="padding:8px 28px 28px;">
<p style="margin:0;font-size:13px;color:#0F172A;">This is an on-page snapshot of the public homepage, robots.txt, and sitemap as fetched on {esc(REPORT_DATE)}. It is not a ranking guarantee and does not measure keyword positions, backlinks, or Google Business Profile performance.</p>
</div>
</footer>
</div>"""


def publish(client: dict, audit: dict) -> dict:
    cid = client["id"]
    name = client["name"]
    site = audit["site_url"]
    title = f"Weekly SEO Report — {name} — {REPORT_DATE}"
    description = f"On-page SEO snapshot for {site} (week of {WEEK_OF})."
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
        "passed": audit["passed"],
        "warns": audit["warns"],
        "fails": audit["fails"],
        "reachable": audit["reachable"],
    }
    if status not in (200, 201) or not isinstance(created, dict) or not created.get("id"):
        result["assignmentNote"] = f"POST /reports failed HTTP {status}"
        return result
    rid = created["id"]
    result["reportId"] = rid
    stored = (created.get("content") or "")
    result["htmlStored"] = bool(stored) and "<div" in stored
    result["portalEnabled"] = bool(created.get("clientPortalEnabled"))

    pstatus, patched = api_send(
        "PATCH",
        f"/reports/{rid}",
        {
            "clientPortalEnabled": True,
            "assignedClients": [cid],
            "assignmentNotes": f"Weekly on-page SEO snapshot for {name}.",
        },
    )
    if pstatus in (200, 201) and isinstance(patched, dict):
        result["portalEnabled"] = bool(patched.get("clientPortalEnabled", True))
        if patched.get("content"):
            result["htmlStored"] = "<div" in patched["content"]
        if patched.get("assignments"):
            result["assignmentLanded"] = any(
                isinstance(a, dict) and a.get("clientId") == cid and not a.get("disassociatedAt")
                for a in patched["assignments"]
            )

    astatus, assigned = pstatus, patched
    gstatus, got = api_get(f"/reports/{rid}/assignments")
    assignments = []
    if isinstance(got, list):
        assignments = got
    elif isinstance(got, dict):
        assignments = got.get("assignments") or got.get("data") or []
        if not assignments and got.get("clientId"):
            assignments = [got]
    active = [
        a
        for a in assignments
        if isinstance(a, dict)
        and a.get("clientId") == cid
        and not a.get("disassociatedAt")
    ]
    result["assignmentLanded"] = bool(active)
    if result["assignmentLanded"]:
        result["assignmentNote"] = f"Assigned (PATCH assignedClients HTTP {astatus}, GET HTTP {gstatus})."
    else:
        result["assignmentNote"] = (
            "RICH_TEXT report was created and should be assigned in Admin → Reports. "
            f"(PATCH assignedClients HTTP {astatus}, GET HTTP {gstatus}.)"
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
                {"client": name, "clientId": cid, "skipped": True, "reason": "missing Credentials → Website URL", "reportId": None}
            )
            print(json.dumps(summaries[-1]))
            continue
        site = normalize_site_url(site)
        print(json.dumps({"event": "audit_start", "client": name, "site": site}))
        audit = audit_site(site)
        print(
            json.dumps(
                {
                    "event": "audit_done",
                    "client": name,
                    "reachable": audit["reachable"],
                    "status": audit["homepage"]["status"],
                    "passed": audit["passed"],
                    "warns": audit["warns"],
                    "fails": audit["fails"],
                    "findingStatuses": [f["status"] + ":" + f["check"] for f in audit["findings"]],
                }
            )
        )
        pub = publish(client, audit)
        summaries.append(pub)
        print(json.dumps({k: v for k, v in pub.items() if k != "html"}))

    out_path = "/tmp/weekly_seo_results.json"
    with open(out_path, "w") as f:
        json.dump(summaries, f, indent=2)
    print(json.dumps({"event": "complete", "resultsPath": out_path, "count": len(summaries)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
