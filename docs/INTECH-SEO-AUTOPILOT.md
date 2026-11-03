# INTECH SEO Autopilot operations

## What runs

`.github/workflows/intech-seo-controller.yml` runs every Monday at 07:00 UTC
and can also be started manually. It uses the existing Google Cloud Workload
Identity Federation provider and service account:

- Provider: `projects/110513102800/locations/global/workloadIdentityPools/intech-github/providers/github`
- Service account: `intech-seo-autopilot@intech-seo-autopilot.iam.gserviceaccount.com`
- Authentication: GitHub Actions OIDC; no service-account key or OAuth secret

Each website is processed independently. The run summary reports `success`,
`failed`, or `insufficient_data` per site. The Markdown report is in
`seo-reports/weekly/<site-id>/report.md`; the combined JSON, CSV exports, and
index are in the same weekly directory. The report artifact and cumulative
history artifact are retained for 90 days.

## Connect Search Console properties

The successful central **Verify Google Search Console connection** run on
2026-10-29 returned all eight properties with `siteFullUser` permission. Their
exact identifiers are already in `seo-sites.json`. This verifies property
visibility via the existing OIDC-authenticated API, but the new weekly
Search Analytics requests still need a run in Actions to validate metrics
collection for each property.

After merging this implementation, run **INTECH SEO Autopilot - all clients**
manually. Confirm each site's report says `ok` or `insufficient_data`;
`not_configured` and `error` are not successful connections. An
`insufficient_data` result means the API call succeeded but returned no
current-period impressions; it is not an access failure.

The API client requests totals, queries, landing pages, countries, and devices
for two adjacent 28-day periods. It excludes the latest four days, matching the
existing working LB Electrical collector, to reduce
partial-data effects, retries temporary 429/5xx responses, and reports
permission and property errors explicitly. An API response with no impressions
is `insufficient_data`; it is not supplemented with estimates.

## Technical crawl and evidence

The read-only crawler checks the homepage, robots.txt, public XML sitemap,
metadata, canonical URLs, headings, image alt attributes, JSON-LD, noindex
directives, mobile viewport declarations, duplicate metadata, same-site
internal links, and HTTP/redirect responses. It follows robots.txt rules and
limits the crawl to 50 pages per site, five sitemap documents, and 5,000
sitemap locations with a short delay. It checks sitemap
URLs as crawl candidates only: sitemap inclusion is not proof of indexing.
Core Web Vitals and Google mobile-usability verdicts are not inferred from
HTML; those require their respective data sources.

Findings carry evidence and a confidence classification. Some metadata or
heading recommendations are heuristic and require a human to assess page
intent. Search CTR comparisons use the site's own observed Search Console
position cohort; they are signals, not guarantees.

Keyword-to-page observations for both periods are preserved in `query-pages.csv`
and the JSON report. Internal-link suggestions use these observed relationships;
queries without a returned page relationship do not receive guessed targets.
An increase in average position number is treated as a ranking decline.

The seed `keywords` drive free keyword discovery using public Google autocomplete
(up to four seeds and two languages per client) and crawled page headings.
Suggestions are deduplicated and flagged when already present in either period's
returned Search Console rows. Absence from those rows does not prove a keyword
has never ranked. Country and language parameters request localization; they do
not guarantee local demand. The undocumented autocomplete endpoint is best effort:
failures are recorded, with heading-derived ideas retained as a fallback.

Review `keyword-ideas.csv` or each site's **New keyword ideas** section. Each idea
records its source, seed, optional source page, and observed-query flag. Search
volume is intentionally blank. Headings are content ideas, not demand evidence;
autocomplete may contain jobs, competitors, or unrelated intent. Human relevance
review is required before implementing any idea. No website edits are performed. Google Ads Keyword Planner is deliberately excluded from
the reporting path while the existing API access tier blocks keyword ideas.

## Add a client

Use **INTECH SEO - onboard client** in Actions. Provide the client's name,
HTTPS root URL, country (`GB`, `LT`, or `EU` where no single country applies),
language codes, business type, and optional comma-separated seed topics.
Provide a GitHub repository only when the website repository is confirmed.
Provide an exact Search Console property only after verifying it.

The workflow opens an onboarding pull request; review and merge it before
monitoring begins. For direct configuration changes, use the same schema in
`seo-sites.json`: a unique kebab-case `id`, `name`, `url`, `domain`, `country`,
`languages`, `business_type`, `keywords`, `gsc_property`, and `repository`.
Run `python -m unittest discover -s tests -v` after changing the registry.

## Historical data and artifacts

Before reporting, the workflow downloads the cumulative JSONL history artifact
from the latest successful run. It stores at most 104 weekly snapshots per
site, with the top 100 current queries and landing pages per snapshot, then
uploads the updated history as a separate 90-day artifact. This
provides a rolling baseline; if no prior artifact is available, the run logs
that it is starting a new baseline. Once no retained artifact is available,
older history cannot be recovered automatically.

## Automatic title and description updates

The crawler and discovery remain read-only. A separate publisher runs after each
audit and may commit **only title and meta-description copy** in configured
Python metadata functions. Visible text, headings, products, URLs, templates,
robots directives, canonicals, schemas and databases are outside its scope.

`seo-publishing.json` maps each configured site to an exact repository, branch,
source file, function, baseline strings, and ordered copy variants. Variants are
written to fit established services and locations. A variant is eligible only
when its configured keyword is returned by autocomplete in the current report;
heading-derived suggestions alone never trigger changes. This is deterministic
copy selection, not unrestricted AI rewriting. Novel keywords without configured
copy stay in the keyword ideas report until a suitable variant is added.

LB Electrical's homepage source was confirmed at
`elieassaf33/LB_Electrical/core/context_processors.py`. Its initial configured
variant uses the observed phrase `electrical testing and inspection`. Its
`deployment_on_push_verified` flag remains false because unattended deployment
has not been established. The other seven sites have no publishing target yet.
Do not infer or enable a deployment mapping from a similar repository name.

The publisher parses Python and changes exactly the configured string values in
the `title` and `description` assignments. Existing source must match the baseline
or a known variant. It preserves other bytes, compiles the resulting file, and
commits the two metadata changes together using the source file's SHA as a
precondition. Unexpected edits, conflicts, old reports (over eight days), and
missing connections block changes. Repeating the same selection is a no-op.
A failed write is not retried automatically; the next run reads the source again.

### Publishing connection requirements

1. Confirm the source repository, metadata location, and page-specific copy for
   each client. Metadata consumed by visible headings is unsuitable for this
   adapter; add a dedicated metadata field first.
2. Install and test the site's existing deployment pipeline, including its
   normal checks and rollback procedure. Only then mark
   `deployment_on_push_verified` true for that branch. The publisher does not
   install server helpers, grant sudo, migrate databases, or deploy via SSH.
3. Store a GitHub App installation token or a fine-grained token as the central
   repository's `SEO_PUBLISH_TOKEN` Actions secret, restricted to the confirmed
   target repositories with Contents write permission. Do not put credentials
   in the registry, source code, reports, or chat. Token rotation/refresh must
   be configured separately if an expiring App token is used.
4. Push this implementation to the central repository and run the workflow.
   Inspect `publishing.md` and `publishing.json` in the weekly report artifact.
   The publisher step reports an error when blocked but does not interrupt audit
   artifact uploads or weekly history restoration.

The publisher distinguishes `preview`, `blocked`, `not_configured`, `error`,
`no_matching_keyword`, `unchanged`, and `committed_pending_deployment`. A source
commit is not proof of deployment: `live_verified` stays false. Confirm the target
pipeline result and rendered metadata separately; no live verification is claimed
by this version. No production deployment has occurred during implementation.

### Local preview

```powershell
python -m scripts.metadata_publisher
# For the existing local LB source, without a publishing credential:
python -m scripts.metadata_publisher --local-site lb-electrical --local-source ../LB_Electrical/core/context_processors.py
```

Preview mode produces a unified diff without writing to client repositories.
Local source overrides are forbidden with `--apply`. In Actions, `--apply` still
requires all publishing connection requirements above.

## Local checks

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m scripts.intech_controller
```

Running the controller locally performs public website reads. For local GSC
collection, set `GCP_USE_ADC=true` and provide local Application Default
Credentials with the Search Console read-only scope. Never store credential
files in this repository.
