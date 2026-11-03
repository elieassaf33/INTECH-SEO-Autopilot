# Free keyword discovery and automatic metadata updates

The Monday Search Console audit remains unchanged and covers all 13 properties.
Its successful completion triggers **Weekly free keyword discovery and metadata
updates**. The previous weekday paid AI content workflow is replaced, so this
path uses no OpenAI API, paid keyword API, or language model.

Each site uses at most four autocomplete seed requests, localized by language and
country. This public, undocumented endpoint is best effort. Ideas and failures
are retained in the workflow artifact; suggestions are not search-volume data.
Only broad configured topics and their online/service variants may change a
homepage. Product-specific and unrelated expansions remain ideas for future
page-specific policies. A candidate's full phrase must already occur in that
site's current visible source text. No opportunity means no change.

Changes are limited to the existing title and description tags. Existing title
wording is retained; a supported keyword can be added only when it fits the
length limit. Descriptions combine the supported phrase with complete sentences
from the site's pinned existing description, with numbers checked against current
visible facts. Visible page text, H1s, links, canonicals, structured data, product
records and checkout remain unchanged. Other Django paths retain their original
metadata through a homepage-only conditional. The two CardBros domains share one
physical slot and are not written twice.

`metadata-targets.json` pins each source, original metadata tags, source digest,
site facts, language, seeds, services and verification URLs. The installed
root-owned `metadata` command accepts only fresh JSON proposals and independently
recomputes and validates copy against the current site. It cannot run submitted
code or arbitrary paths/services. Unknown source changes, inaccessible sites,
unsupported phrases and failed checks stop that site without stopping others.

The existing dedicated SSH secret and pinned host settings are reused. No new
personal access token or client-repository write access is needed. Publication
backs up exact source, writes only the two managed tag regions, verifies live
metadata, and rolls back on failure. Netlify retains unchanged assets and function source, and restores its previous
deployment if checks fail. When its function cache is unavailable, the worker
re-uploads a root-pinned archive whose function source matches the deployed Git
commit. The archive and source entry are hash-checked; memory, Node runtime and
region must match production before a draft can be published. The upload explicitly selects the existing Node.js runtime rather than Netlify's
newer default. Site environment variables are preserved. A successful change
rebases the approved recovery manifest so Monday recovery does not undo it. Each
physical site has a seven-day cooldown. These are production source updates, not
commits to the client repositories; future client releases must reconcile source
and refresh the pinned baseline.

Repository Actions variable `SEO_METADATA_PUBLISH_ENABLED=true` enables automatic
publication after a successful audit. Manual dispatch defaults to research-only;
use `publish=true` to test publication. The former `SEO_GROWTH_PUBLISH_ENABLED`
flag has no effect on this workflow. Removing or setting the metadata flag false
stops automatic writes while discovery continues.

Artifacts `free-keyword-metadata-<run-id>` contain `proposals.json` (ideas, selected
copy, skipped/blocked results) and `publication.json` (verified updates, cooldowns,
backups and failures). Runs execute on GitHub and the VPS; the owner's computer
need not be running. Evaluation is weekly; changes occur only when suitable.
