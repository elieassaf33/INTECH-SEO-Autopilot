# INTECH SEO Autopilot

## Monitoring

`seo-sites.json` contains 13 GSC properties grouped into 11 client identities.
Every Monday at 07:00 UTC, the central workflow audits them all. Manual runs are
read-only. No client workflow installation is needed. The schedule uses the
default branch; unmerged PR changes are not scheduled production behavior.

Reports include property-level status, access checks, homepage technical checks,
Google indexed-version diagnostics, two adjacent seven-day windows of web-search
performance, and client-grouped recommendations. Windows end three days before
the Pacific date to allow reporting lag. Aggregate clicks, impressions, CTR and
position come from separate dimensionless `byProperty` queries; query/page rows
are never summed into site totals. Position improvement is previous minus current.
CTR changes are percentage points. Missing rows are not proof of zero traffic.

Query/page retrieval uses 25,000-row pages and a 100,000-row cap per window;
reports flag the cap. Google still returns partial top rows. Recommendations are
heuristics requiring review: clicks down 30% with a baseline of five, CTR below
2% at positions 1-10 with 50 impressions, or ranking positions 5-20 with ten
impressions. Declines on disappeared rows are investigation prompts only.

Transient HTTP 429/5xx and transport timeouts have three bounded attempts. 403 and hidden-property 404 are
not retried or presented as empty traffic. Errors are isolated per property and
per metric section. No-data is distinct from access-denied, partial and error.
The workflow retains artifacts before failing its health gate when any property
has failed access or incomplete diagnostics. A green old workflow alone did not
prove that all properties succeeded: inspect per-property results.

Artifacts (90 days): `report.json`, `report.md`, timestamped snapshots,
`health.json`, `remediation-plan.json`, and `access-actions.json`/`access-actions.md`.
The access checklist names each denied property, observed HTTP status and ADC
service-account email (when available), with exact permission and recheck steps.
Other setup/transport errors remain separate; they are not mislabeled as missing
GSC permissions. Each run has its own artifact name.
Adjacent-window comparisons use Google history directly. Snapshots are retained
as run artifacts; no permanent time-series database or year-over-year trend
engine is implemented.

## Google service account

The configured identity is
`intech-seo-autopilot@intech-seo-autopilot.iam.gserviceaccount.com`.
GitHub OIDC uses provider
`projects/110513102800/locations/global/workloadIdentityPools/intech-github/providers/github`.
Retain restrictive repository/ref conditions on that provider. Do not broaden
trust to get a feature-branch test working. No service-account JSON keys are used.

Enable Search Console API in that Google project. In each GSC property go to
Settings > Users and permissions and grant that service account access. Full user
access is the recommended role for monitoring and URL Inspection; ownership is
not required. Windsor authorization is a different identity and grants no ADC
access. The verification workflow checks every registry property and emits
`gsc-access.json`, including HTTP status and the required action on access denial.

The five added properties initially returned 403 in the baseline. This was
resolved externally: [live audit 41026334512](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41026334512)
verified `siteFullUser` access and successful indexed-version diagnostics for
all 13 properties. Seven properties returned traffic data; Tesla EU and the five
additions returned authorized no-data. The health gate passed and permission
checklist was empty. No GSC permission action remains from that run.

If a denial recurs, verify the exact property and grant the identity above access
through Search Console Settings > Users and permissions, then rerun verification.
Search Console permission is separate from Cloud IAM. Do not create a broader
Cloud IAM role to fix a per-property GSC denial.

## Technical checks and limits

Checks follow up to five redirects between the configured domain and its www
alias. Other hosts require an explicit `allowed_redirect_hosts` registry entry.
A shared client ID or repository does not imply that domains are interchangeable.
Reports preserve redirect evidence and inspect the final homepage; they never
change redirects. Fetches reject non-public addresses and non-HTTP(S) schemes,
use timeouts and cap bodies at 1.5 MB. A truncated, failed or non-HTML response
does not produce missing-metadata findings.

Checks include nonempty title/description/canonical, HTML/HTTP canonical conflicts,
noindex hints, Googlebot robots rules, robots-declared sitemap discovery,
sitemap XML validation, and homepage internal-link opportunities. A missing
robots.txt is allowed. Off-host sitemap/canonical references require review,
not automatic replacement. Sitemap indexes are recognized but not recursively
crawled. Internal-link suggestions mean a sitemap URL is not directly linked
from the homepage, not that it is an orphan. No arbitrary full-site crawl,
JavaScript rendering, broken-link crawl, or
live Google indexability test is claimed. HTTP Link canonical headers are checked
alongside head metadata. Matching header and HTML targets are not conflicts;
body metadata is ignored. Fragment-bearing canonical targets require review.
Truncated robots or sitemap bodies make the audit partial rather than producing
a false validity verdict. URL Inspection describes Google's
indexed version and cannot submit an indexing request.

## Registry and onboarding

Run **INTECH SEO - onboard client**, review its generated PR, and merge through
normal review. A new property is monitored automatically after merge. Required
fields are name and HTTPS root; set the exact `gsc_property` for GSC monitoring.
Use `client_id` to group multiple properties into one business. Repository
mapping, default branch and production-source evidence require separate review.
Do not infer a repository from a domain name. `check_registry.py` rejects loss of
any of the original 13 properties while allowing additions.

The verified defaults are `master` for `commerce_well` and `alisos_foto_django`,
and `main` for the other mapped repositories. Proposal publication rechecks the
actual GitHub default branch. The owner confirmed `alisos_foto_django` as the photography production source
and `ainos_plauku` (`main`) as Tvari Kirpeja's production source on 30 October 2026.
Photography also matches four live HTML markers. Exact deployed commits remain
unverified; remediation stays disabled for all clients. See [verification evidence](VERIFICATION-2026-10-30.md).

## Safe remediation

Monitoring produces a blocked proposal plan; it never writes client repositories.
All clients start with `remediation_enabled: false`; `remediation-policies.json`
is empty. There are no unattended SEO changes, automatic merges or deployments.

The manual remediation workflow runs only reviewed code on central `main`, in
the `seo-remediation` GitHub environment. Configure required reviewers and disable
self-review before enabling publication. The workflow does not create those
protection rules. Normal PR branch protections must require review and CI on
client repositories; draft status alone is not a merge permission control.

The first adapter supports only insertion of a missing title or description in
an explicitly identified static HTML file. Dynamic Django/React templates,
canonicals, robots, sitemaps, routing and domain changes deliberately fail closed.
Those need a source-specific reviewed patch and separate tests. No speculative copy is
invented: an approved metadata value is mandatory. The pipeline is:

1. Match a fresh (at most seven days) issue to its exact GSC property and URL.
2. Require a confirmed-by-owner repository mapping, explicit remediation enable,
   reviewed deployment triggers bound to an exact commit, target file and reviewed SHA-256 source hash.
3. Recheck the actual default branch, target type and current source hash.
4. Insert one escaped tag; validate the parsed result and single-insertion invariant.
5. Check deterministic branches for existing PRs in all states. Reuse existing
   PRs; do not reset stale branches or reopen closed proposals automatically.
6. On explicit publish, create only a feature branch and **draft PR**. Never merge.

No client code, dependency installers or test commands execute with a write
credential. The controlled adapter validates its patch offline. Client application
CI and human review are still required before merging; arbitrary remote app tests
are not yet automated. There are no enabled automatic policies matching current findings. The owner
confirmed `https://cardbrostcg.com` as CardBros primary on 30 October 2026; both
CardBros registry entries record that `primary_origin`. The registry validates
that a primary belongs to a registered property of the same client and that
client members do not declare conflicting primaries. It is accepted as a
canonical target without authorizing any cross-domain redirects.

[CardBros draft PR #1](https://github.com/elieassaf33/pokemon/pull/1) is a separately
reviewed source-specific homepage fix: a base-template block plus an explicit
`https://cardbrostcg.com/en/` canonical in the homepage template. Four real-template
render tests cover both hosts, query/host isolation, and other-page inheritance.
No product, account or checkout canonical policy is inferred. Nothing has been
merged or deployed; production remains unchanged until a reviewed release.

A reviewed policy has this shape (example only; do not enable blindly):

```json
{
  "gsc_property": "sc-domain:example.com",
  "repository": "owner/verified-site",
  "default_branch": "actual-branch",
  "url": "https://example.com/",
  "issue": "missing_description",
  "file": "index.html",
  "source_sha256": "64 lowercase hex characters from the reviewed file bytes",
  "reviewed_commit": "40 lowercase hex characters from the reviewed default-branch commit",
  "approved_value": "Human-approved accurate description",
  "branch_push_reviewed": true
}
```

Dry-run with `python scripts/remediation.py --report path/to/report.json`.
Publish adds `--publish`; it still requires all policy gates. Feature-branch push
and PR events can trigger client hosting automation, so inspect hosting and
workflow triggers before setting `branch_push_reviewed`. Never enable a policy
if that could deploy production automatically. No such deployment audit is
claimed for the current disabled clients.

## Cross-repository credentials

Central `GITHUB_TOKEN` is limited to the central repository; it is not a client
write credential. Prefer a GitHub App installed only on explicitly selected
client repositories, granting Metadata read, Contents read/write and Pull requests
read/write. No Administration, Actions write, Secrets, Deployments or organization
permissions are needed. The workflow mints and revokes an installation token via
the pinned `actions/create-github-app-token` action; set environment variables
`SEO_APP_ID`, `SEO_TARGET_REPOSITORIES` (explicit repository names), and environment
secret `SEO_APP_PRIVATE_KEY`. Empty target scope is rejected.

Alternatively set environment secret `SEO_REMEDIATION_TOKEN` to a short-lived
fine-grained PAT restricted to those same selected repositories and permissions.
Do not use a classic all-repository PAT. Keep the token in the protected environment,
never Git, command-line arguments, report files or client test environments.
Use `gh secret set SEO_REMEDIATION_TOKEN --env seo-remediation --repo elieassaf33/INTECH-SEO-Autopilot`
for an interactive secret prompt. App/PAT setup is pending; no new secret was created.

## Validation

Install `pip install -r requirements.txt`, then run:

```text
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
python scripts/check_registry.py
```

CI runs tests on Python 3.12 and 3.14. Integration tests use a local HTTP server
and fake Google responses, including a 13-property run with one access denial.
No production data is touched by tests. Workflows use immutable action SHAs,
read-only monitoring permissions, timeouts, concurrency control and no persisted
checkout credentials. The separate onboarding workflow has only the central
Contents/PR write access needed to propose a registry change.

API references: [Search Analytics](https://developers.google.com/webmaster-tools/v1/searchanalytics/query),
[URL Inspection](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect).

Canonical handling follows [Google's HTML and HTTP canonical documentation](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls).
An absent explicit canonical is a review opportunity, not proof that Google
cannot index a page or that a particular primary domain should be selected.
