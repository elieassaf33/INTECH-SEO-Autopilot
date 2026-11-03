# INTECH SEO Autopilot

Weekly monitoring of 13 Google Search Console properties, grouped into 11
clients, followed by automatic production metadata recovery for all 13 properties.
The production worker restores approved missing metadata against pinned VPS
templates and Netlify releases, backs up changes, checks live pages and rolls
back failed repairs. Other SEO findings remain recommendations.

The separate static-HTML draft-PR adapter remains disabled. Production recovery
uses its own restricted SSH worker, not the draft-PR credential path.

See [setup, safeguards and limits](docs/INTECH-SEO-AUTOPILOT.md) and
[verified status and blockers](docs/VERIFICATION-2026-10-30.md).

Tests: `python -m unittest discover -s tests -v`.

After each successful Monday audit, free keyword discovery evaluates all 13
properties and the restricted metadata worker can update supported **titles and
meta descriptions only**. Visible page text is preserved. The former paid AI
content workflow is replaced. See [free metadata automation](docs/FREE-METADATA-AUTOMATION.md).

Daily health checks cover 31 configured pages. GitHub issues notify the owner of
incidents, and a private offline HTML dashboard shows keyword opportunities,
metadata history and 28-day Search Console comparisons.
See [monitoring and dashboard](docs/SEO-INSIGHTS.md).
