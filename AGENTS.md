# test-automation

Weekly Connection Inc client **visibility reports**.

## Run

```bash
pip install -r requirements.txt
python3 weekly_seo_report.py
```

`weekly_seo_report.py` is a thin entrypoint. All logic is in `visibility_report/`.

Automation prompt: [AUTOMATION_PROMPT.md](./AUTOMATION_PROMPT.md)

## Package layout

| Module | Responsibility |
|---|---|
| `visibility_report/config.py` | Pilots list, dates, portal API base URL |
| `visibility_report/env.py` | Runtime Secret env var names |
| `visibility_report/portal.py` | Portal HTTP + client custom fields |
| `visibility_report/crawl.py` | Homepage fetch, HTML parse, robots, sitemap |
| `visibility_report/offers.py` | Real services (portal → schema → sitemap → Gemini) |
| `visibility_report/google_apis.py` | PageSpeed, Places, Geocoding, Gemini, GSC, GA4 |
| `visibility_report/scoring.py` | Search/AI query builders + score helpers |
| `visibility_report/audit.py` | End-to-end visibility audit |
| `visibility_report/report_html.py` | Oasbit-style RICH_TEXT HTML |
| `visibility_report/publish.py` | Create + assign portal reports |
| `visibility_report/main.py` | Pilot loop + JSON summary |

## v1 Runtime Secrets

| Secret name | Used for |
|---|---|
| `PORTAL_API_KEY` | Connection Inc portal API |
| `pagespeed_api` | PageSpeed Insights |
| `gemini_api` | Gemini + Google Search grounding |
| `places_api` | Places API (Google Business Profile) |
| `geocoding_api` | Geocoding API |
| `search_console_api` | Search Console API (OAuth / service account JSON) |
| `analytics_data_api` | Google Analytics Data API (OAuth / service account JSON) |
| `analytics_property_id` | GA4 property ID (`123456789` or `properties/123456789`) |
| `custom_search_api` | Not used (full-web CSE unavailable for new engines) |
| `maps_javascript_api` | Not used (browser-only) |

Optional: `GEMINI_MODEL` (default `gemini-3.6-flash`).

### Per-client overrides (portal custom fields)

| Custom field name | Example | Purpose |
|---|---|---|
| `Services` | `FHA loans, Refinance, VA loans` | Preferred Offers + search queries |
| `GA4 Property ID` | `365023674` | Client’s GA4 property |
| `Search Console Site URL` | `sc-domain:adamzmortgage.com` | Exact GSC property URL |

### Search Console + Analytics credentials

Unlike PageSpeed, **Search Console and GA4 Data APIs require OAuth**, not a plain API key. Store **service account JSON** in `search_console_api` / `analytics_data_api`, grant that email access on each property, and set `analytics_property_id` (or the client custom field).

## Data sources

| Section | Source |
|---|---|
| Site health | PageSpeed Insights |
| Search sample | Gemini + Google Search grounding |
| Search Console metrics | GSC searchAnalytics (28 days) when auth succeeds |
| Analytics | GA4 runReport sessions/users (28 days) when auth succeeds |
| Listings | Places API |
| Offers | Portal `Services` field → schema → sitemap service URLs → Gemini (never raw H2/H3 slogans) |

## Pilot clients

Configured in `visibility_report/config.py`:

```python
PILOTS = [
    ("Adam Zeman", "cmkoitqae0001ib04j8hrefa9"),
]
```

## Template reference

[Oasbit visibility report](https://oasbit.com/114/4757a659-1a96-4425-947d-4ffae49f87c2)
