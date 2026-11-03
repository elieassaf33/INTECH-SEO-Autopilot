# INTECH SEO Autopilot

Central SEO monitoring and configured metadata updates for INTECH client websites. The Monday GitHub
Actions workflow creates separate Markdown reports per website, CSV exports,
and a combined JSON status report. Technical crawling and Search Console
collection are isolated per client so one site's failure does not stop the rest.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m scripts.intech_controller
```

Local Search Console collection requires valid Google Application Default
Credentials with the Search Console read-only scope and `GCP_USE_ADC=true`.
GitHub Actions uses the existing Google Cloud Workload Identity Federation
provider and service account; it does not use a JSON key.

## Configuration and operation

See [the operations guide](docs/INTECH-SEO-AUTOPILOT.md). All eight exact
Search Console property IDs are registered and were visible to the existing
OIDC-authenticated service account with `siteFullUser` permission. The
new Search Analytics request path still requires a successful weekly run.
Future blank properties are reported as `not_configured`; inaccessible
properties are reported as errors.

Reports are written under `seo-reports/weekly/`; cumulative JSONL history is
under `seo-reports/history/` and is restored from the previous successful
Actions artifact before each scheduled run.

## Free keyword discovery

Weekly runs discover keyword candidates from public Google autocomplete and
crawled page headings, using each client's seed topics, language and country.
No Ads account, API key, or paid keyword service is needed. Results appear in
`keyword-ideas.csv`, per-site Markdown reports, and the combined JSON report.
Autocomplete is an undocumented, best-effort source and may be unavailable;
errors are visible and do not stop the technical audit. Suggestions require
relevance review and do not include search-volume estimates. Configured metadata
variants can be applied by the separate publishing stage below.

## Automatic titles and descriptions

The weekly workflow now runs `python -m scripts.metadata_publisher --apply` after
reporting. It selects configured title/description variants when matching
keywords are returned by autocomplete. It does not rewrite visible page text,
create pages, or add arbitrary keywords to copy. No paid language model is used.
New discovered phrases without a configured variant remain suggestions.

Publishing requires a confirmed source target in `seo-publishing.json`, a
repository-scoped `SEO_PUBLISH_TOKEN` Actions secret with Contents write access,
and a verified deployment pipeline on the target branch. These connections are
not installed by this change: LB Electrical has a preview target but is blocked;
the other seven sites are unconfigured. Changes remain local in this checkout.

See `seo-reports/weekly/publishing.md` and `publishing.json` for per-site results.
A commit awaiting deployment is never reported as a live website update.
