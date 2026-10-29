# INTECH SEO Autopilot

The central registry is `seo-sites.json`. Every Monday at 07:00 UTC the
`INTECH SEO Autopilot - all clients` workflow audits every registered client.
Manual runs are also supported. Download `intech-weekly-seo-report` from the
Actions run for `report.json` and `report.md` (90-day retention).

## Onboarding

Run **INTECH SEO - onboard client** in Actions. Supply the name, HTTPS root,
optional repository, and exact Search Console property (`sc-domain:example.com`
or the exact URL-prefix property including its trailing slash). Review and merge
the generated registry PR. No client workflow or code change is needed.
Alternatively add the same fields directly to `seo-sites.json` through a PR.

The current registry has no `gsc_property` values. Configure the actual verified
properties before expecting live keyword reports; the controller deliberately
does not guess which properties the service account can access.

## Google access

Enable the Search Console API in Google Cloud. Configure GitHub Workload Identity
Federation restricted to this repository, and set repository variables
`GCP_WIF_PROVIDER` and `GCP_SERVICE_ACCOUNT`. Grant the service account access to
each client's Search Console property. The existing verification workflow can
list authorized properties. No service account JSON secret is required.

For local read-only runs install `pip install -r requirements.txt`, configure
Application Default Credentials, set `GCP_USE_ADC=true`, then run
`python scripts/intech_controller.py`. Never commit credential files.

## Weekly keyword analysis

Each client compares seven days ending three days before the current Pacific
date with the immediately preceding seven days. Requests use finalized web
search data grouped by query and landing page, paginated at 25,000 rows with a
100,000-row cap per window. Reports flag the cap. The Search Console API returns
top rows and can omit data even below this cap; these are not site-wide totals.
See the [Google API reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query).

JSON includes clicks, impressions, CTR, position, absolute click and impression
changes, percentage click changes (null when the baseline is zero), and position
improvement (positive means better). Newly observed and no-longer-observed rows
are labeled; absence is not proof of zero traffic. No-data, missing setup and
API errors are distinct statuses. A client failure does not stop other clients,
and a technical audit failure does not prevent its GSC analysis.

Recommendations are deterministic heuristics, not ranking guarantees:

- High priority: clicks down at least 30% from a baseline of at least five clicks.
- Medium priority: at least 50 impressions, position 1-10 and CTR below 2%; review title and snippet relevance.
- Medium priority: at least 10 impressions and position 5-20; review query coverage and internal links.

Every recommendation includes the keyword, landing page and supporting metrics.
Markdown shows the top 20 per client, ordered by priority then impressions; JSON
contains all recommendations and comparison rows. Treat disappearance-based
declines as investigation prompts because API coverage can vary. This is actual
observed search traffic, not Keyword Planner search-volume research.

## Development and safety

Run `python -m unittest discover -s tests -v` for offline mocked API tests.
Tests also run on pull requests and before weekly authentication and analysis.
Reports are ignored by Git and kept as Actions artifacts.

Monitoring only reads client websites and Search Console. Recommendations require
human review. It never modifies client code, production data or deploys websites.
