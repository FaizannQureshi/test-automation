"""Full visibility audit orchestration."""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from .crawl import (
    PageParser,
    canonical_href,
    count_sitemap_urls,
    fetch,
    meta_content,
    robots_blocks_all,
    schema_types,
    session,
    sitemap_urls_from_robots,
)
from .env import ga_configured, gemini_key, google_key, gsc_configured
from .google_apis import (
    brand_mentioned,
    fetch_analytics,
    fetch_search_console,
    gemini_ask,
    gemini_search_ranking,
    geocode_address,
    owned_citations,
    pagespeed,
    places_lookup,
)
from .offers import discover_offers, service_like_pages
from .portal import origin, site_host
from .scoring import (
    build_ai_prompts,
    build_search_queries,
    clamp_score,
    metric_status,
    score_from_ratio,
)

def audit_visibility(
    site_url: str,
    business_name: str,
    *,
    ga_property: str | None = None,
    gsc_site: str | None = None,
    client: dict | None = None,
) -> dict:
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
    offers = discover_offers(
        client=client,
        brand=brand,
        host=host,
        json_ld=parser.json_ld,
        page_urls=page_urls,
        homepage_html=homepage.get("text") or "",
    )
    service_pages = service_like_pages(page_urls, host, offers)
    extra_ps_urls = [u for u in service_pages if u != final_url][:2]

    # PageSpeed
    ps_home_m = pagespeed(final_url, strategy="mobile")
    ps_home_d = pagespeed(final_url, strategy="desktop")
    ps_extra: list[dict] = []
    for u in extra_ps_urls:
        ps_extra.append({"url": u, **pagespeed(u, strategy="mobile")})

    # Search sample via Gemini + Google Search grounding (queries from real offers)
    queries = build_search_queries(brand, host, offers)
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

    # Search Console + Google Analytics (Runtime Secrets: search_console_api, analytics_data_api)
    gsc_data = fetch_search_console(final_url, gsc_override=gsc_site)
    ga_data = fetch_analytics(ga_property)

    # Component scores
    search_score = score_from_ratio(first_page_hits, len(queries))
    if gsc_data.get("ok") and gsc_data.get("queries"):
        gsc_on_page = sum(
            1 for q in gsc_data["queries"][:10] if (q.get("position") or 99) <= 10
        )
        gsc_score = score_from_ratio(gsc_on_page, min(len(gsc_data["queries"]), 10))
        search_score = max(search_score, gsc_score)
        if search_method.startswith("Gemini"):
            search_method = "Gemini sample + Search Console (28-day)"
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
    if not gsc_data.get("ok"):
        if gsc_configured():
            gaps.append("Search Console is configured but returned no data for this property")
        else:
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
            "note": (
                f"Web-search sample via {search_method}."
                if gsc_data.get("ok")
                else f"Web-search sample via {search_method}. Not Search Console ranks."
            ),
        }
    )
    if gsc_data.get("ok"):
        at_a_glance.append(
            {
                "label": "Search Console clicks (28 days)",
                "value": str(gsc_data.get("total_clicks", 0)),
                "status": metric_status(
                    "higher_is_better", gsc_data.get("total_clicks", 0), good=50, warn=10
                ),
                "note": (
                    f"{gsc_data.get('total_impressions', 0)} impressions · "
                    f"{gsc_data.get('period', '')} · property {gsc_data.get('siteUrl', '')}"
                ),
            }
        )
    if ga_data.get("ok"):
        at_a_glance.append(
            {
                "label": "Analytics sessions (28 days)",
                "value": str(ga_data.get("sessions", 0)),
                "status": metric_status(
                    "higher_is_better", ga_data.get("sessions", 0), good=500, warn=100
                ),
                "note": (
                    f"{ga_data.get('active_users', 0)} active users · "
                    f"{ga_data.get('pageviews', 0)} pageviews · {ga_data.get('period', '')}"
                ),
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
    if gsc_data.get("ok"):
        other_facts.append(
            {
                "label": "Search Console",
                "status": "On track",
                "detail": (
                    f"{gsc_data.get('total_clicks', 0)} clicks and "
                    f"{gsc_data.get('total_impressions', 0)} impressions in the last 28 days."
                ),
            }
        )
    elif gsc_configured():
        other_facts.append(
            {
                "label": "Search Console",
                "status": "Watch",
                "detail": gsc_data.get("error") or "search_console_api set but no data returned.",
            }
        )
    else:
        other_facts.append(
            {
                "label": "Search Console",
                "status": "Watch",
                "detail": "Not connected — add search_console_api Runtime Secret.",
            }
        )
    if ga_data.get("ok"):
        other_facts.append(
            {
                "label": "Google Analytics",
                "status": "On track",
                "detail": (
                    f"{ga_data.get('sessions', 0)} sessions, "
                    f"{ga_data.get('active_users', 0)} active users (28 days)."
                ),
            }
        )
    elif ga_configured():
        other_facts.append(
            {
                "label": "Google Analytics",
                "status": "Watch",
                "detail": ga_data.get("error") or "analytics_data_api set but no data returned.",
            }
        )
    elif ga_secret():
        other_facts.append(
            {
                "label": "Google Analytics",
                "status": "Watch",
                "detail": "Set analytics_property_id (GA4 property ID) alongside analytics_data_api.",
            }
        )
    else:
        other_facts.append(
            {
                "label": "Google Analytics",
                "status": "Watch",
                "detail": "Not connected — add analytics_data_api and analytics_property_id.",
            }
        )

    # Offers already discovered above (portal → schema → sitemap → Gemini)
    # strip internal source keys for HTML display
    offer_rows = [
        {"name": o.get("name"), "kind": o.get("kind") or "Service", "score": o.get("score")}
        for o in offers
    ]

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
        "offers": offer_rows[:12],
        "offer_sources": sorted({o.get("source") for o in offers if o.get("source")}),
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
            "gsc_ok": bool(gsc_data.get("ok")),
            "gsc_error": (gsc_data.get("error") or "")[:120] if not gsc_data.get("ok") else "",
            "ga": ga_configured(),
            "ga_ok": bool(ga_data.get("ok")),
            "ga_error": (ga_data.get("error") or "")[:120] if not ga_data.get("ok") else "",
            "pagespeed": bool(google_key("PAGESPEED")),
            "gemini": bool(gemini_key()),
            "places": bool(google_key("PLACES")),
            "geocoding": bool(google_key("GEOCODING")),
            "search_method": search_method,
        },
        "gsc_queries": gsc_data.get("queries") or [],
    }

