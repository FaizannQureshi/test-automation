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
| `search_console_api` | Search Console API (service account JSON) |
| `analytics_data_api` | Google Analytics Data API (service account JSON) |
| `custom_search_api` | Not used (full-web CSE unavailable for new engines) |
| `maps_javascript_api` | Not used (browser-only) |

Optional: `GEMINI_MODEL` (default `gemini-3.6-flash`). Optional global fallback: `analytics_property_id` (prefer per-client portal fields).

### Per-client overrides (portal custom fields)

| Custom field name | Example | Purpose |
|---|---|---|
| `Services` | `FHA loans, Refinance, VA loans` | Preferred Offers + search queries (optional) |
| `GA4 URL` / `GA4 Property ID` | analytics admin URL or `458571033` | Client’s GA4 property |
| `GSC URL` / `Search Console Site URL` | GSC users URL or `sc-domain:example.com` | Exact GSC property |
| `GBP Name` / `GBP URL` | Profile name or business.google.com link | Improves Listings / Places match |
| `Primary City` / `Main Keyword` | `Roseville, CA` / `mortgage lender` | Better local search queries |

### Search Console + Analytics credentials

Unlike PageSpeed, **Search Console and GA4 Data APIs require OAuth**, not a plain API key. Store **service account JSON** in `search_console_api` / `analytics_data_api`, and invite that JSON’s `client_email` on each client’s GSC + GA. Property IDs come from the portal client fields (no global `analytics_property_id` required).
## Data sources

| Section | Source |
|---|---|
| Site health | PageSpeed Insights (skips legal/utility URLs like terms/privacy) |
| Search sample | Gemini + Google Search grounding |
| Search Console metrics | GSC searchAnalytics (28 days); spam/non-Latin queries filtered |
| Analytics | GA4 runReport sessions/users (28 days) when auth succeeds |
| Listings | Places API with website/name confidence scoring (+ portal GBP fallback) |
| Offers | Portal `Services` field → schema → sitemap service URLs → Gemini refine |

## Pilot clients

Configured in `visibility_report/config.py`. Current pilots: **Amy DeBusk** (`amydebuskhomeloans.com`), **Chris Nieberlein** (`chrisnieberlein.com`), resolved by website host at runtime.

### GSC / GA access (important)

The weekly job authenticates with the **service account email inside** your `search_console_api` / `analytics_data_api` JSON (`client_email`, usually `…@….iam.gserviceaccount.com`).

Adding `ai.seo@connectionincorporated.com` in the Google UI only helps if that address is the same as `client_email` in the JSON. If the JSON is a GCP service account, invite **that** `client_email` (not the human Workspace inbox) as:

- Search Console → Users → Restricted or Full
- GA4 → Account (or Property) access → Viewer

The run summary prints `service_account_email` in `apiNotes` so you know exactly which address to invite.
## Template reference

[Oasbit visibility report](https://oasbit.com/114/4757a659-1a96-4425-947d-4ffae49f87c2)
