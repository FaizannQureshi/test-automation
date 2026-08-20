"""Oasbit-style RICH_TEXT HTML report builder (portal-safe inline CSS)."""

from __future__ import annotations

import html as htmlmod
from typing import Any
from urllib.parse import urlparse

from .config import REPORT_DATE, TODAY
from .portal import site_host
def esc(s: Any) -> str:
    return htmlmod.escape("" if s is None else str(s), quote=True)


def status_color(status: str) -> str:
    return {
        "On track": "#6EE7B7",
        "Watch": "#FCD34D",
        "Fix": "#FCA5A5",
    }.get(status, "#94A3B8")


# Oasbit palette (dark theme — matches oasbit.com visibility report)
C_BG = "#101218"
C_PANEL = "#0B1220"
C_CARD = "#161B26"
C_CELL = "#1E293B"
C_BORDER = "#334155"
C_TEXT = "#F8FAFC"
C_BODY = "#E8E6F2"
C_MUTED = "#9CA3AF"
C_VIOLET = "#C4B5FD"
C_LINK = "#A5B4FC"


# ---------------------------------------------------------------------------
# NOTE on inline styling constraints (Connection Inc RICH_TEXT sanitizer)
# ---------------------------------------------------------------------------
# Survives: color, background (solid hex), font-*, line-height, letter-spacing,
#           text-align, width, height, padding, border, border-radius, border-collapse
# Stripped: margin, display (flex/grid/inline-block), text-transform, tr background,
#           single-side borders, gradients/rgba backgrounds
# Portal also forces dark navy on table areas — always set color+background on
# every td/th and wrap copy in <span style="color:…"> so text stays visible.


def spacer(px: int) -> str:
    return f'<div style="height:{px}px;background:{C_BG};"></div>'


def lit(text: Any, color: str = C_TEXT) -> str:
    return f'<span style="color:{color};">{esc(text)}</span>'


def cell(
    content: str,
    *,
    header: bool = False,
    bg: str = C_CELL,
    color: str = C_TEXT,
    align: str = "left",
    size: str = "14px",
    weight: str = "400",
) -> str:
    tag = "th" if header else "td"
    return (
        f'<{tag} style="padding:10px 12px;color:{color};background:{bg};'
        f'border:1px solid {C_BORDER};text-align:{align};font-size:{size};font-weight:{weight};">'
        f"{content}</{tag}>"
    )


def score_tier_color(score: int) -> str:
    if score >= 70:
        return "#6EE7B7"
    if score >= 40:
        return "#FCD34D"
    return "#FCA5A5"


def priority_badge(priority: str) -> str:
    p = (priority or "").lower()
    if "first" in p:
        bg, fg = "#7F1D1D", "#FCA5A5"
    elif "important" in p:
        bg, fg = "#78350F", "#FCD34D"
    else:
        bg, fg = "#1E3A5F", "#93C5FD"
    label = esc((priority or "").upper())
    return (
        f'<span style="padding:3px 10px;font-size:10px;font-weight:700;'
        f'letter-spacing:0.06em;color:{fg};background:{bg};border:1px solid {C_BORDER};'
        f'border-radius:999px;">{label}</span>'
    )


def score_card(label: str, score: int, desc: str) -> str:
    color = score_tier_color(score)
    return f"""<table style="width:100%;border-collapse:collapse;background:{C_CARD};border:1px solid {C_BORDER};border-radius:12px;">
<tr>
{cell(lit(label, C_TEXT), bg=C_CARD, weight="700")}
{cell(lit(str(score), color), bg=C_CARD, color=color, align="right", weight="800", size="22px")}
</tr>
</table>
{spacer(6)}
<p style="padding:0 12px;font-size:12px;color:{C_MUTED};line-height:1.45;background:{C_CARD};">{lit(desc, C_MUTED)}</p>
{spacer(8)}
<div style="height:8px;background:{C_CELL};border-radius:6px;">
<div style="height:8px;width:{score}%;background:{color};border-radius:6px;"></div>
</div>
{spacer(6)}
<p style="padding:0;font-size:10px;color:{C_MUTED};letter-spacing:0.08em;background:{C_CARD};">{lit("SCORE OUT OF 100", C_MUTED)}</p>"""


def score_cards_row(cards: list[tuple[str, int, str]]) -> str:
    width = 100 // max(len(cards), 1)
    tds = "".join(
        f'<td style="width:{width}%;padding:8px;background:{C_PANEL};">{score_card(l, s, d)}</td>'
        for l, s, d in cards
    )
    return f'<table style="width:100%;border-collapse:collapse;background:{C_PANEL};"><tr>{tds}</tr></table>'


def overall_badge(overall: int) -> str:
    color = score_tier_color(overall)
    size = 168
    return f"""<div style="width:{size}px;height:{size}px;border:10px solid {color};border-radius:999px;background:{C_PANEL};text-align:center;line-height:{size}px;">
{lit(str(overall), C_TEXT)}<span style="font-size:15px;color:{C_MUTED};">/100</span>
</div>
{spacer(10)}
<p style="text-align:center;font-size:12px;color:{C_MUTED};letter-spacing:0.08em;background:{C_PANEL};">{lit("OVERALL", C_MUTED)}</p>"""


def nav_pills() -> str:
    labels = ["Scores", "Facts", "Offers", "Search", "Improve", "Compare", "Next"]
    cells = ""
    for lab in labels:
        cells += (
            f'<td style="padding:4px 6px;background:{C_PANEL};">'
            f'<span style="padding:6px 12px;font-size:11px;font-weight:600;color:{C_MUTED};'
            f'background:{C_CARD};border:1px solid {C_BORDER};border-radius:999px;">'
            f"{lit(lab, C_MUTED)}</span></td>"
        )
    return f'<table style="width:100%;border-collapse:collapse;background:{C_PANEL};"><tr>{cells}</tr></table>'


def scores_section(scores: dict, overall: int) -> str:
    channel_cards = score_cards_row(
        [
            (
                "Search",
                scores.get("search", 0),
                "Whether Google and similar search engines can find, understand, and rank your pages for the work you sell.",
            ),
            (
                "Listings",
                scores.get("listings", 0),
                "Whether your Google Business Profile, map pin, and name-address-phone details match and can be confirmed.",
            ),
            (
                "AI answers",
                scores.get("ai_answers", 0),
                "Whether ChatGPT, Gemini, and other answer engines name or cite you on buyer questions in your category.",
            ),
        ]
    )
    website_cards = score_cards_row(
        [
            (
                "Site health",
                scores.get("site_health", 0),
                "Page speed, HTTPS, crawlability, and whether important URLs load cleanly on mobile.",
            ),
            (
                "Content",
                scores.get("content", 0),
                "Whether key pages have unique copy, accurate business facts, and proof.",
            ),
            (
                "Structure",
                scores.get("structure", 0),
                "Sitemaps, headings, schema, and information architecture.",
            ),
        ]
    )
    return f"""<div style="background:{C_PANEL};border:1px solid {C_BORDER};border-radius:16px;padding:24px;">
<p style="padding:0 0 14px;font-size:22px;font-weight:700;color:{C_TEXT};background:{C_PANEL};">{lit("Your scores", C_TEXT)}</p>
<table style="width:100%;border-collapse:collapse;background:{C_PANEL};">
<tr>
<td style="width:200px;padding:0 20px 0 0;background:{C_PANEL};">{overall_badge(overall)}</td>
<td style="padding:0;background:{C_PANEL};">
<p style="padding:0 0 10px;font-size:12px;color:{C_VIOLET};letter-spacing:0.08em;background:{C_PANEL};">{lit("CHANNELS", C_VIOLET)}</p>
{channel_cards}
</td>
</tr>
</table>
{spacer(18)}
<p style="padding:0 0 10px;font-size:12px;color:{C_VIOLET};letter-spacing:0.08em;background:{C_PANEL};">{lit("WEBSITE", C_VIOLET)}</p>
{website_cards}
</div>"""


def metric_card(label: str, value: str, status: str, note: str) -> str:
    st_color = status_color(status)
    return f"""<div style="padding:14px 16px;background:{C_CARD};border:1px solid {C_BORDER};border-radius:12px;">
<p style="padding:0 0 4px;font-size:13px;color:{C_MUTED};background:{C_CARD};">{lit(label, C_MUTED)}</p>
<p style="padding:0 0 6px;font-size:22px;font-weight:700;color:{C_TEXT};background:{C_CARD};">{lit(value, C_TEXT)}</p>
<span style="padding:3px 10px;font-size:11px;font-weight:700;border-radius:999px;color:{C_BG};background:{st_color};">{lit(status, C_BG)}</span>
<p style="padding:8px 0 0;font-size:12px;color:{C_BODY};line-height:1.4;background:{C_CARD};">{lit(note, C_BODY)}</p>
</div>"""


def search_hit_card(rank: int, query: str, score: int, note: str) -> str:
    sc_color = score_tier_color(score) if score else C_MUTED
    return f"""<td style="width:20%;padding:6px;background:{C_PANEL};">
<div style="padding:12px;background:{C_CARD};border:1px solid {C_BORDER};border-radius:12px;">
<p style="padding:0;font-size:13px;color:{C_VIOLET};background:{C_CARD};">{lit(f"{rank:02d}", C_VIOLET)}</p>
<p style="padding:6px 0;font-size:13px;font-weight:600;color:{C_TEXT};background:{C_CARD};">{lit(query, C_TEXT)}</p>
<p style="padding:0;font-size:20px;font-weight:700;color:{sc_color};background:{C_CARD};">{lit(str(score), sc_color)}</p>
<p style="padding:6px 0 0;font-size:11px;color:{C_MUTED};background:{C_CARD};">{lit(note, C_MUTED)}</p>
</div>
</td>"""


def build_html(client_name: str, business: str, audit: dict) -> str:
    brand = audit.get("brand") or business or client_name
    host = audit.get("host") or site_host(audit["site_url"])
    site = audit["site_url"]
    overall = audit["overall_score"]
    scores = audit["scores"]
    prepared = TODAY.strftime("%b %d, %Y")
    opportunity = audit.get("opportunity") or ""
    opp_lead = opportunity.split(".")[0] + "." if opportunity else ""
    opp_rest = opportunity[len(opp_lead) :].strip()

    glance_cards = ""
    glance = audit.get("at_a_glance") or []
    for i in range(0, len(glance), 2):
        pair = glance[i : i + 2]
        cells = ""
        for m in pair:
            cells += f"""<td style="width:50%;padding:8px;background:{C_BG};">
{metric_card(m.get("label", ""), str(m.get("value", "")), m.get("status") or "Watch", m.get("note") or "")}
</td>"""
        if len(pair) == 1:
            cells += f'<td style="width:50%;padding:8px;background:{C_BG};"></td>'
        glance_cards += f'<table style="width:100%;border-collapse:collapse;background:{C_BG};"><tr>{cells}</tr></table>'

    facts = ""
    other_facts = audit.get("other_facts") or []
    for i, f in enumerate(other_facts):
        st = f.get("status") or "Watch"
        st_c = status_color(st)
        facts += f"""<div style="padding:12px 14px;background:{C_CARD};border:1px solid {C_BORDER};border-radius:12px;">
<table style="width:100%;border-collapse:collapse;background:{C_CARD};"><tr>
<td style="padding:0;background:{C_CARD};">{lit(f.get("label", ""), C_TEXT)}</td>
<td style="padding:0;text-align:right;background:{C_CARD};"><span style="font-size:11px;font-weight:700;color:{st_c};">{lit(st.upper(), st_c)}</span></td>
</tr></table>
<p style="padding:8px 0 0;font-size:13px;color:{C_BODY};line-height:1.45;background:{C_CARD};">{lit(f.get("detail", ""), C_BODY)}</p>
</div>"""
        if i < len(other_facts) - 1:
            facts += spacer(10)

    offers = ""
    offer_list = audit.get("offers") or []
    for i, o in enumerate(offer_list):
        sc = o.get("score")
        sc_txt = lit(str(sc), C_MUTED) if sc is not None else lit("0", C_MUTED)
        offers += f"""<table style="width:100%;border-collapse:collapse;background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;">
<tr>
{cell(lit(o.get("name", ""), C_TEXT) + " " + sc_txt, bg=C_CARD)}
{cell(lit(o.get("kind", ""), C_MUTED), bg=C_CARD, align="right", color=C_MUTED, size="12px")}
</tr>
</table>"""
        if i < len(offer_list) - 1:
            offers += spacer(8)

    search_obs = audit.get("search_observations") or []
    ranked = sorted(search_obs, key=lambda x: x.get("score") or 0, reverse=True)
    top_hits = [o for o in ranked if (o.get("score") or 0) > 0][:5]
    search_cards = ""
    if top_hits:
        for row_start in range(0, len(top_hits), 5):
            row_items = top_hits[row_start : row_start + 5]
            cells = ""
            for j, o in enumerate(row_items, row_start + 1):
                cells += search_hit_card(j, o.get("query", ""), o.get("score") or 0, o.get("note", ""))
            search_cards += f'<table style="width:100%;border-collapse:collapse;background:{C_BG};"><tr>{cells}</tr></table>'
            if row_start + 5 < len(top_hits):
                search_cards += spacer(8)

    search_rows = ""
    for idx, o in enumerate(search_obs, 1):
        sc = o.get("score") or 0
        sc_c = score_tier_color(sc) if sc else C_MUTED
        search_rows += f"""<tr>
{cell(lit(f"{idx:02d}", C_VIOLET), bg=C_CELL, color=C_VIOLET, size="13px")}
{cell(lit(o.get("query", ""), C_TEXT), bg=C_CELL, weight="600")}
{cell(lit(str(sc), sc_c), bg=C_CELL, color=sc_c, weight="700")}
{cell(lit(o.get("note", ""), C_BODY), bg=C_CELL, color=C_BODY, size="13px")}
</tr>"""

    improve_blocks = ""
    improvements = audit.get("improvements") or []
    for i, imp in enumerate(improvements):
        pages = "".join(
            f'<p style="padding:0 0 4px;font-size:13px;background:{C_CARD};"><a href="{esc(p)}" style="color:{C_LINK};">{lit(p, C_LINK)}</a></p>'
            for p in imp.get("pages") or []
        )
        improve_blocks += f"""<table style="width:100%;border-collapse:collapse;background:{C_CARD};border:1px solid {C_BORDER};border-radius:12px;">
<tr>
<td style="width:4px;padding:0;background:{C_LINK};"></td>
<td style="padding:16px 18px;background:{C_CARD};">
<p style="padding:0 0 8px;background:{C_CARD};">{priority_badge(imp.get("priority", ""))}</p>
<p style="padding:0 0 4px;font-size:11px;font-weight:700;letter-spacing:0.06em;color:{C_VIOLET};background:{C_CARD};">{lit(f"{imp.get('category', '').upper()} · {imp.get('priority', '').upper()}", C_VIOLET)}</p>
<p style="padding:0 0 8px;font-size:16px;font-weight:600;color:{C_TEXT};background:{C_CARD};">{lit(imp.get("title", ""), C_TEXT)}</p>
<p style="padding:0 0 10px;font-size:14px;color:{C_BODY};line-height:1.5;background:{C_CARD};">{lit(imp.get("finding", ""), C_BODY)}</p>
<p style="padding:0 0 6px;font-size:12px;font-weight:700;color:{C_TEXT};letter-spacing:0.04em;background:{C_CARD};">{lit("WHAT WE RECOMMEND", C_TEXT)}</p>
<p style="padding:0 0 10px;font-size:14px;color:{C_BODY};line-height:1.5;background:{C_CARD};">{lit(imp.get("recommendation", ""), C_BODY)}</p>
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
            f'<a href="{esc(link)}" style="color:{C_LINK};">{lit(c.get("name", ""), C_LINK)}</a>'
            if link
            else lit(c.get("name", ""), C_TEXT)
        )
        comp_rows += f"""<tr>
{cell(lit(f"{idx:02d}", C_VIOLET), bg=C_CELL, color=C_VIOLET)}
{cell(name_cell, bg=C_CELL, weight="600")}
{cell(lit(c.get("site", ""), C_BODY), bg=C_CELL, color=C_BODY)}
{cell(lit(c.get("notes", ""), C_MUTED), bg=C_CELL, color=C_MUTED, size="13px")}
</tr>"""

    steps = ""
    next_steps = audit.get("next_steps") or []
    for i, s in enumerate(next_steps):
        steps += f"""<table style="width:100%;border-collapse:collapse;background:{C_CARD};border:1px solid {C_BORDER};border-radius:12px;">
<tr>
{cell(lit(f"{s.get('rank', 0):02d}", C_MUTED), bg=C_CARD, color=C_MUTED, weight="700", size="18px")}
<td style="padding:14px 16px;background:{C_CARD};">
<p style="padding:0 0 4px;font-size:11px;font-weight:700;color:{C_LINK};background:{C_CARD};">{lit(f"{s.get('badge', '')} · {s.get('effort', '')}", C_LINK)}</p>
<p style="padding:0 0 6px;font-size:15px;font-weight:600;color:{C_TEXT};background:{C_CARD};">{lit(s.get("title", ""), C_TEXT)}</p>
<p style="padding:0;font-size:13px;color:{C_BODY};line-height:1.45;background:{C_CARD};">{lit(s.get("detail", ""), C_BODY)}</p>
</td>
</tr>
</table>"""
        if i < len(next_steps) - 1:
            steps += spacer(12)

    unreachable = ""
    if not audit.get("reachable"):
        unreachable = f"""<div style="padding:12px 14px;background:#7F1D1D;border:1px solid #991B1B;border-radius:8px;">
{lit(f"Site unreachable. Could not fully load {site}. Scores reflect partial data.", "#FCA5A5")}
</div>{spacer(16)}"""

    h2 = f"padding:0 0 14px;font-size:18px;font-weight:700;color:{C_TEXT};background:{C_BG};"
    sub = f"padding:0 0 12px;font-size:13px;color:{C_MUTED};background:{C_BG};"
    wrap = f"padding:0 28px;background:{C_BG};"

    return f"""<div style="padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:{C_TEXT};background:{C_BG};line-height:1.5;">
<div style="background:{C_PANEL};color:{C_TEXT};padding:32px 28px 28px;">
<p style="padding:0 0 6px;font-size:10px;letter-spacing:0.22em;color:{C_VIOLET};background:{C_PANEL};">{lit("AI AND SEARCH SNAPSHOT", C_VIOLET)}</p>
<h1 style="padding:0 0 10px;font-size:28px;line-height:1.2;color:{C_TEXT};background:{C_PANEL};">{lit("How visible is ", C_TEXT)}{lit(brand, C_VIOLET)}?</h1>
<p style="padding:0 0 16px;font-size:15px;color:{C_BODY};line-height:1.55;background:{C_PANEL};"><strong style="color:{C_TEXT};">{lit(opp_lead, C_TEXT)}</strong> {lit(opp_rest, C_BODY)}</p>
<p style="padding:0;font-size:13px;color:{C_MUTED};background:{C_PANEL};">{lit("Prepared on ", C_MUTED)}{lit(prepared, C_TEXT)}{lit(" · Website ", C_MUTED)}<a href="{esc(site)}" style="color:{C_LINK};">{lit(host, C_LINK)}</a></p>
</div>
<div style="height:4px;background:{C_LINK};"></div>
{spacer(16)}
<div style="{wrap}">{nav_pills()}</div>
{spacer(24)}
<div style="{wrap}">
{unreachable}
<h2 style="{h2}">{lit("Scores", C_TEXT)}</h2>
<p style="{sub}">{lit("Channels are how people discover you. Site scores are how ready the website is when they arrive. Empty bars were not measured in this snapshot.", C_MUTED)}</p>
{scores_section(scores, overall)}
</div>
{spacer(28)}
<div style="{wrap}">
<h2 style="{h2}">{lit("Facts · At a glance", C_TEXT)}</h2>
<p style="{sub}">{lit("Measured numbers get a chart. Plain facts stay in the list below.", C_MUTED)}</p>
{glance_cards}
{spacer(16)}
<h3 style="padding:0 0 10px;font-size:14px;font-weight:700;color:{C_VIOLET};background:{C_BG};">{lit("Other facts", C_VIOLET)}</h3>
{facts}
</div>
{spacer(28)}
<div style="{wrap}">
<h2 style="{h2}">{lit("Offers · What you offer", C_TEXT)}</h2>
<p style="{sub}">{lit("Services and products discovered from the client portal, site schema, sitemap service URLs, or AI extraction — not homepage marketing headlines.", C_MUTED)}</p>
{offers or f"<p style=\"color:{C_MUTED};background:{C_BG};\">{lit('No sellable services detected. Add a portal custom field Services (comma-separated) for this client.', C_MUTED)}</p>"}
</div>
{spacer(28)}
<div style="{wrap}">
<h2 style="{h2}">{lit("Search · Where you show up", C_TEXT)}</h2>
<p style="{sub}">{lit("Search observations from this snapshot — not estimated ranks unless a rank was actually recorded.", C_MUTED)}</p>
{search_cards}
{spacer(12) if search_cards else ""}
<p style="padding:0 0 10px;font-size:14px;font-weight:700;color:{C_VIOLET};background:{C_BG};">{lit("Search observations", C_VIOLET)}</p>
<table style="width:100%;border-collapse:collapse;background:{C_CELL};border:1px solid {C_BORDER};border-radius:10px;font-size:14px;">
<thead><tr>
{cell(lit("#", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
{cell(lit("Query", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
{cell(lit("Score", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
{cell(lit("Note", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
</tr></thead>
<tbody>{search_rows}</tbody>
</table>
</div>
{spacer(28)}
<div style="{wrap}">
<h2 style="{h2}">{lit("Improve · What to improve", C_TEXT)}</h2>
<p style="{sub}">{lit("Open a row for the finding, the recommendation, and the pages it touches.", C_MUTED)}</p>
{improve_blocks or f"<p style=\"color:{C_MUTED};background:{C_BG};\">{lit('No critical improvements flagged this week.', C_MUTED)}</p>"}
</div>
{spacer(28)}
<div style="{wrap}">
<h2 style="{h2}">{lit("Compare · How you compare", C_TEXT)}</h2>
<p style="{sub}">{lit("Firms that showed up in the same sampled searches and AI answers. Scores appear only when we measured them.", C_MUTED)}</p>
<table style="width:100%;border-collapse:collapse;background:{C_CELL};border:1px solid {C_BORDER};border-radius:10px;font-size:14px;">
<thead><tr>
{cell(lit("#", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
{cell(lit("Company", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
{cell(lit("Site", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
{cell(lit("Notes", C_VIOLET), header=True, bg=C_CELL, color=C_VIOLET, size="12px")}
</tr></thead>
<tbody>{comp_rows or f"<tr>{cell(lit('No competitors observed in this sample.', C_MUTED), bg=C_CELL)}</tr>"}</tbody>
</table>
</div>
{spacer(28)}
<div style="{wrap}">
<h2 style="{h2}">{lit("Next · Your next steps", C_TEXT)}</h2>
<p style="{sub}">{lit("Work from the top if you want the fastest lift.", C_MUTED)}</p>
{steps}
</div>
{spacer(20)}
<div style="border:1px solid {C_BORDER};background:{C_PANEL};padding:16px 28px;">
<p style="padding:0;font-size:12px;color:{C_MUTED};line-height:1.5;background:{C_PANEL};">{lit(f"Private AI and search snapshot for {client_name}. Generated {REPORT_DATE} by Connection Inc weekly automation. Search observations use Gemini with Google Search grounding — sample-based, not guaranteed Google positions. Connect Search Console and Analytics for historical data.", C_MUTED)}</p>
</div>
</div>"""

