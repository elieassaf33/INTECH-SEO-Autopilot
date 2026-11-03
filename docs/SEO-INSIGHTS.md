# Daily monitoring and measured SEO results

The weekly Monday audit discovers keywords for free and evaluates titles and
meta descriptions across 31 source-verified pages on 13 Search Console properties.
Coverage includes homepages, services, categories and products. Visible text is
preserved. A candidate must be supported by that page's existing content; no
suitable candidate means no publication. Page enrollment is bounded and reviewed
against canonical URLs and pinned production sources, rather than arbitrary URLs.

The daily `seo-insights.yml` workflow runs at 06:15 UTC and after metadata runs
or failed upstream workflows. It checks availability, duplicate/missing metadata,
noindex directives, publishing failures, stale audits and incomplete journal
operations. Transient HTTP failures are retried. A single managed GitHub issue
notifies the repository owner, updates when incidents change and closes on
recovery. GitHub notification delivery follows the owner's notification settings.

Every publication records its old and new metadata in a durable server journal.
Seven earlier publications were reconstructed from the existing ledger and pinned
original values, and are explicitly labelled with that provenance. An uncertain
publication is flagged for review rather than silently treated as successful.

Measured results compare exact-page Search Console totals for 28 days before and
28 days after publication, excluding publication day. Dates use Search Console's
Pacific timezone; final results wait a further three days. Each page is held
through that interval so weekly runs do not repeatedly change it. Comparisons need
at least 100 impressions in each period and ten combined clicks. Missing or sparse
data, overlapping changes and access failures are explicit states. Observed changes
are descriptive, not proof that metadata caused ranking or traffic changes.

Download the private `seo-insights-dashboard-<run-id>` artifact from a **Daily SEO
health and private dashboard** Actions run, unzip it and open `index.html`.
The report includes site/search filters, health, opportunities, old/new copy,
measured results and coverage. It works offline without external requests and
includes downloadable JSON. Artifacts are retained for 90 days; server history
persists independently. Reports can contain business performance data: share them
only with intended recipients. Overlapping GSC properties are not summed.

Existing restricted SSH and Google workload identity are reused. No paid keyword
API, model API, email service or public dashboard hosting is required. The new
`insights` forced command exports only bounded history and approved page fields.
The publisher verifies installed code and configuration hashes, preserves shared
Django template rules and rebases recovery checks after successful publication.
Unknown source drift blocks publication until the pinned baseline is reconciled.

Set `SEO_METADATA_PUBLISH_ENABLED=false` to suspend automatic metadata writes.
Discovery, daily monitoring and private reporting continue. Manual metadata runs
default to research-only; use `publish=true` for publication. The owner's computer
does not need to stay on.
