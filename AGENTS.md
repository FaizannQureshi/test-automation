# test-automation

Weekly Connection Inc client **visibility reports** via `weekly_seo_report.py` (Oasbit-style template).

## Run

```bash
pip install -r requirements.txt
python3 weekly_seo_report.py
```

Automation prompt: [AUTOMATION_PROMPT.md](./AUTOMATION_PROMPT.md)

## v1 Runtime Secrets

| Secret name | Used for |
|---|---|
| `PORTAL_API_KEY` | Connection Inc portal API |
| `pagespeed_api` | PageSpeed Insights |
| `gemini_api` | Gemini + Google Search grounding |
| `places_api` | Places API (Google Business Profile) |
| `geocoding_api` | Geocoding API |
| `search_console_api` | Search Console API (see note below) |
| `analytics_data_api` | Google Analytics Data API (see note below) |
| `analytics_property_id` | GA4 property ID (`123456789` or `properties/123456789`) |
| `custom_search_api` | Not used (full-web CSE unavailable for new engines) |
| `maps_javascript_api` | Not used (browser-only) |

Optional: `GEMINI_MODEL` (default `gemini-3.6-flash`).

### Search Console + Analytics credentials

Unlike PageSpeed, **Search Console and GA4 Data APIs require OAuth**, not a plain API key in the URL.

Store **service account JSON** (minified one line) in Runtime Secrets `search_console_api` and `analytics_data_api`, then:

1. Enable **Search Console API** and **Google Analytics Data API** in GCP.
2. Add the service account email to each client’s **Search Console** property (Settings → Users).
3. Add the same email to the client’s **GA4** property (Admin → Property access management).
4. Set `analytics_property_id` to that client’s GA4 property ID.

If you only store a short GCP API key string, the script will detect the secret as set but `gsc_ok` / `ga_ok` will be false with an auth error in `apiNotes`.

## Data sources

| Section | Source |
|---|---|
| Site health | PageSpeed Insights |
| Search sample | Gemini + Google Search grounding |
| Search Console metrics | GSC searchAnalytics (28 days) when auth succeeds |
| Analytics | GA4 runReport sessions/users (28 days) when auth succeeds |
| Listings | Places API |
| Content / structure | Homepage crawl + sitemap |

## Pilot clients

```python
PILOTS = [
    ("Adam Zeman", "cmkoitqae0001ib04j8hrefa9"),
]
```

## Template reference

[Oasbit visibility report](https://oasbit.com/114/4757a659-1a96-4425-947d-4ffae49f87c2)
