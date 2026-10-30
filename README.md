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
