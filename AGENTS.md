# test-automation

Weekly Connection Inc client **visibility reports** via `weekly_seo_report.py` (Oasbit-style template).

## Architecture (hybrid)

| Layer | Responsibility |
|---|---|
| **Cursor Automation** | Install deps, run `python3 weekly_seo_report.py`, return JSON summary |
| **`weekly_seo_report.py`** | API calls, scoring, HTML template, portal POST + assignment |
| **Runtime Secrets (v1)** | API keys injected as env vars — never logged |

The agent is a **runner only**. Report logic stays in the committed Python script.

## Run

```bash
pip install -r requirements.txt
python3 weekly_seo_report.py
```

Automation prompt: see [AUTOMATION_PROMPT.md](./AUTOMATION_PROMPT.md).

## v1 Runtime Secrets (your naming)

| Secret name | Used for |
|---|---|
| `PORTAL_API_KEY` | Connection Inc portal API (Personal secret) |
| `pagespeed_api` | PageSpeed Insights |
| `gemini_api` | Gemini AI + Google Search grounding for ranking samples |
| `places_api` | Places API (New) — Google Business Profile |
| `geocoding_api` | Geocoding — verify listing address |
| `custom_search_api` | Reserved (Google no longer allows full-web CSE for new engines) |
| `maps_javascript_api` | Not used by this script (browser-only) |

Legacy uppercase names (`GEMINI_API_KEY`, `GOOGLE_PAGESPEED_API_KEY`, etc.) also work as fallbacks.

Optional: `GEMINI_MODEL` (default `gemini-3.6-flash`).

Later (not wired yet): `GOOGLE_SEARCH_CONSOLE_CREDENTIALS_JSON`, `GOOGLE_ANALYTICS_PROPERTY_ID`.

## Data sources in each report

| Section | Source |
|---|---|
| Scores (Search, Listings, AI, Site health, Content, Structure) | Computed from API + crawl data |
| Facts / At a glance | PageSpeed, sitemap crawl, Gemini samples |
| Offers | Homepage headings |
| Search | Gemini + Google Search grounding (10-query sample) |
| Improve / Compare / Next | Derived findings + competitor domains from samples |

Search Console and Analytics show as “not connected” until those credentials are added.

## Pilot clients

Only clients in `PILOTS` inside `weekly_seo_report.py` are processed:

```python
PILOTS = [
    ("Adam Zeman", "cmkoitqae0001ib04j8hrefa9"),
]
```

Expand after verifying the template in Admin → Reports.

## Report template reference

[Oasbit visibility report sample](https://oasbit.com/114/4757a659-1a96-4425-947d-4ffae49f87c2)

Sections: Scores · Facts · Offers · Search · Improve · Compare · Next
