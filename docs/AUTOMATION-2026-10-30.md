# Production automation enabled — 30 October 2026

The owner authorized automatic application and deployment after checks pass.
Central PRs [#8](https://github.com/elieassaf33/INTECH-SEO-Autopilot/pull/8)
and [#9](https://github.com/elieassaf33/INTECH-SEO-Autopilot/pull/9) are merged.
PR #8 included the previous platform PR #7; that superseded PR was closed.

## Weekly operation

Every Monday at 07:00 UTC (09:00 Lithuania winter time, 10:00 summer time),
the central main workflow audits all 13 Search Console properties. Its successful
completion starts `Automatic production SEO repairs`. The repair workflow also
requires the latest completed main audit to have passed within 24 hours and runs
all 65 tests before invoking the installed worker through a forced-command key.

All 13 properties / 11 clients have production recovery policies:

- Nine VPS clients / ten properties: exact approved template metadata recovery.
- INTECH Lithuania and Europe: full pinned Netlify release recovery, preserving
  both languages and the `google-reviews` function. All 22 deployed HTML pages
  outside 404 documents have live checks and metadata recovery variants.
- Tvari Kirpeja: pinned Netlify release recovery for its three HTML pages,
  plus recovery when the approved sitemap file disappears.

These policies recover missing title, description and canonical snippets from
approved working source. They recognize tag removal and removal of an otherwise
empty complete metadata line. Unrelated source changes, changed metadata values,
unknown issues and normal application releases require baseline review; they do
not authorize overwriting a newer site. Robots, content/keyword optimization,
arbitrary broken links and general application fixes remain outside this adapter.

## Deployed fixes

- [CardBros client PR #1](https://github.com/elieassaf33/pokemon/pull/1): merged
  after four real-template tests and client CI passed. The worker deployed only
  its two template files. Both `.com/en/` and `.co.uk/en/` now declare the approved
  `https://cardbrostcg.com/en/` homepage canonical. Product/other-page canonical
  policies and redirects were not changed. The first verification attempt failed
  and rolled back; a subsequent guarded application verified both public pages.
- [Tvari Kirpeja client PR #1](https://github.com/elieassaf33/ainos_plauku/pull/1):
  merged after its two tests and CI passed. The deployed index matched repository
  source exactly before the single canonical insertion. The draft release was
  checked before publication, including a sitemap listing the three verified
  public HTML pages and unchanged privacy/cookie pages. The subsequent successful
  Git production release `6ae4b9db97f27cbe4345fddc` is the pinned recovery baseline.

## Verification and recovery

- 65 local tests; Python 3.12/3.14 PR CI; registry validation, compileall and
  actionlint passed. Four CardBros and two Tvari source-specific tests passed.
- All 14 worker/Netlify unit tests passed on the production Linux server.
- An all-client dry run verified all 11 client bundles and 35 public pages,
  with no excluded properties or blocked results.
- [Initial upgraded main audit](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41079885627)
  passed. Its chained [VPS repair workflow](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41080309976)
  passed on retry after the successful guarded CardBros deployment.
- Final all-property main audit: [41083766523](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41083766523)
  passed. Its downloaded artifact contains 13 properties / 11 clients,
  `unhealthy_properties: []`, and no missing-canonical findings.
- Its automatically chained [production repair run 41084147409](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41084147409)
  passed. The downloaded report confirms `apply: true`, all 11 clients healthy,
  35 successful live-page checks, and no blocked or excluded clients. Both
  installed worker hashes matched the tested main-branch code.

Worker/config paths are `/usr/local/lib/intech-seo-repairs/` and
`/etc/intech-seo-repairs/manifest.json`. Only a server administrator can modify
installed code or the allowed source snapshots. VPS backups and timestamped
reports are under `/var/lib/intech-seo-repairs/`; Actions retains reports for
90 days. Netlify recovery retains and restores the previous published deployment
on failed verification. Normal releases need a fresh approved baseline.

The dedicated SSH key rejects arbitrary commands and forwarding. Host keys are
pinned. The Netlify credential remains in a root-only server file and is never
given to Actions. The separate static-HTML draft-PR adapter remains disabled;
`production_repair_enabled` records the installed worker's independent scope.
