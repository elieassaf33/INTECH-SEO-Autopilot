# Weekday keyword research and content publishing

The owner authorized weekday research and automatic website updates for all 13
properties, and configured repository secret `OPENAI_API_KEY` on 30 October 2026.

`weekday-keyword-growth.yml` runs Tuesdays and Thursdays at 07:30 UTC (09:30
Lithuania winter time, 10:30 summer time), independently of the owner's PC. It
requires the latest completed main audit to have passed within the past seven
days. Manual dispatch defaults to research-only; `publish: true` enables the
same bounded production publisher. `limit` allows a small credential smoke test.

For each property, the job combines actual Search Console queries from the latest
weekly report with the current original homepage and one AI web search. Search
Console impressions are observed site impressions, not market search volume;
there is no connected keyword-volume provider. Actual search-tool source URLs
are retained alongside keyword opportunities, copy, factual review and token usage.
The implementation follows OpenAI's [web search](https://developers.openai.com/api/docs/guides/tools-web-search)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
documentation. API authentication is injected only into the research step.

The writer selects one genuinely relevant customer question and drafts a heading
plus one concise paragraph in the existing homepage language. It must quote facts
from that same site's original page, cannot invent offerings, prices, credentials,
locations, availability or benefits, and cannot include HTML or template code.
A separate model call checks factual support, language, relevance and duplication;
deterministic validation checks source quotes, new numbers, output lengths and
keyword repetition. Refused/rejected suggestions are recorded without publication.
Transport/setup failures are explicit blocked results. There are at most 26 model
calls and 13 hosted web searches per full run; API usage is separately billed.

The installed root-owned publisher accepts only fresh checked text and a known
property ID. `keyword-publishing-policies.json` pins each allowed homepage source,
path, locale and service. It appends/replaces one marked content section, preserving
every other source byte, and restricts Django output to the exact homepage path.
CardBros's two properties share one physical template: `.com` publishes the shared
English section and `.co.uk` remains a separately researched alias. Each physical
homepage slot has a 14-day cooldown. Research still runs during the cooldown.

VPS publication backs up the exact source, changes only the bounded section,
restarts mapped services, and verifies live metadata and the rendered new copy.
Netlify publication copies the complete existing file digest and function/config
references into a draft, changes one HTML file, verifies that runtime bundles are
unchanged, then publishes and checks the live pages. Any failed post-publication
check rolls back the source/release. Unknown source changes, new Netlify files,
function/runtime drift, locked deployments and concurrent releases stop that target.

Successful verified updates refresh the root-owned recovery manifest to accept
only the new approved source/release. Monday's repair workflow therefore does not
restore old copy over a legitimate weekday update. The production SSH key allows
only `apply`, `check`, and the bounded `growth` command, without a general shell,
arbitrary uploads, paths, service commands, or executable model output.

Publication history, original-file backups and Netlify rollback receipts are
retained under `/var/lib/intech-seo-repairs/`. GitHub retains complete research and
publication artifacts for 90 days. Content edits are deployed scoped homepage
source changes, not automatic commits to client repository default branches;
the root-owned snapshots and artifacts record them. Normal unrelated site releases
still require source/baseline reconciliation. This does not guarantee rankings,
create arbitrary landing pages, or publish large volumes of generated articles.
