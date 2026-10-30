# Verification and remaining work

## Registry reconciliation

Main at `720c8af` already includes merged PR #5 and all 13 properties. PR #4
contained an eight-property-era mapping delta; it was closed as superseded rather
than merged. PR #6 was updated in place, preserving all properties and adding
explicit client identities, verified default branches and disabled remediation.
No pull request has been merged by this work.

## Live baseline evidence

[Read-only main audit 40961889656](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/40961889656)
used the configured Google service account on 29 October 2026 UTC. Its artifact
contains all 13 property results. That old workflow exits successfully even when
individual properties return errors; the proposed health gate corrects this.

| Property | Client/source | Default branch | Historical baseline | Latest verified access/data |
|---|---|---|---|---|
| lbelectrical.uk | LB Electrical / LB_Electrical | main | OK | Full user; traffic data |
| getintech.lt | INTECH / commerce_well | master | OK | Full user; traffic data |
| getintech.eu | INTECH / commerce_well | master | OK | Full user; traffic data |
| alisosfotografija.lt | Alisos / alisos_foto_django (owner-confirmed) | master | OK | Full user; traffic data |
| klaipedosaliejus.lt | Klaipedos Aliejus / klaipedos_aliejus | main | OK | Full user; traffic data |
| jegaainis.lt | Jegaainis / jegaainis | main | OK | Full user; traffic data |
| cardbrostcg.com | CardBros / pokemon | main | OK | Full user; traffic data |
| teslaeu.eu | Tesla EU / nemokek.lt | main | No query data | Full user; no data |
| tvarikirpeja.lt | Tvari Kirpeja / ainos_plauku | main | HTTP 403 | Full user; no data |
| naturalusmaistas.lt | Naturalus Maistas / naturalus_maistas | main | HTTP 403 | Full user; no data |
| cardbrostcg.co.uk | CardBros / pokemon | main | HTTP 403 | Full user; no data |
| grikiudievas.lt | Grikiu Dievas / grikiu_dievas | main | HTTP 403 | Full user; no data |
| thefurrytale.com | The Furry Tale / thefurrytale | main | HTTP 403 | Full user; no data |

All repository names above are under `elieassaf33`. Default branches were read
from the authenticated GitHub repository API, not inferred from naming.
A local read-only technical audit reached all 13 homepages with HTTP 200 after
redirects. It found missing canonicals on both CardBros domains, and missing
canonical plus unavailable sitemap on Tvari Kirpeja. Other suggestions are
homepage-to-sitemap internal-link opportunities, not proven orphan pages.

## Production-source evidence

`alisos_foto_django` uses `master`. The live photography HTML matches its
`templates/base.html` markers `20261018-phone-menu-centered`,
`20261019-mobile-polish`, `fonts/geist-variable.woff2`, and
`max-image-preview:large`. This is strong source correlation, not proof of the
exact deployed commit. The owner confirmed this as the active production repository on 30 October 2026.
The same confirmation maps Tvari Kirpeja to `elieassaf33/ainos_plauku`, whose
`main` default branch was verified through the authenticated GitHub API.
No automated writes are enabled; exact deployed revisions are still unverified.

Both CardBros roots redirect to `/en/` on their own domain, both return matching
store metadata, and each sitemap lists its own domain's `/en/`. Neither returned
a canonical tag. The `pokemon` default-branch template
`cards/templates/cards/base.html` has the same title/description and no canonical;
`pokemonstore/urls.py` explicitly redirects the root to `/en/`. No cross-domain
redirect is observed. No primary domain was chosen and no canonical/redirect fix
PR was created: selecting a cross-domain policy would be speculative.

## Implemented versus pending

Implemented in the platform PR: separate property aggregates, isolated access
and section failures, bounded retries, indexed-version diagnostics, client-grouped
reports, health gate and report snapshots, safer technical checks, registry
validation, and a disabled-by-default static HTML metadata proposal adapter.
The adapter has source-hash checks, deterministic duplicate detection, controlled
patch validation and draft PR creation; it never runs client code with tokens.

The new implementation was also executed in
[feature-branch audit 40963315211](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/40963315211).
OIDC succeeded without changing its trust configuration. The report contains all
13 properties and 11 client identities; seven properties have real independent
aggregates and successful URL Inspection, Tesla EU has authorized no-data with
successful inspection, and the five additions are not visible to this identity
(`sites.get` HTTP 404, versus Search Analytics HTTP 403 in the baseline). The
artifact was uploaded before the health gate exited with exactly five unhealthy
properties. This is an intentional failing health signal, not a successful audit
of the denied properties.

[PR test run 40963314743](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/40963314743)
passed Python 3.12 and 3.14 integration/unit tests. Local actionlint, registry
validation, compileall and disabled-policy dry-run also passed. The hardened monitoring code with explicit 404 guidance and modern pinned
Node 24 actions was verified in
[audit 41021681010](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41021681010):
setup, tests, OIDC, all-property audit and artifact publication succeeded; only
the health gate failed, correctly identifying exactly the five access denials.
All 13 technical audits completed. The downloaded JSON was checked for 13
properties, 11 clients, eight authorized properties and five explicit
`access_denied` results. This verifies the monitoring implementation against
real service-account credentials without broadening access or modifying data.

Repository metadata inspection also confirmed there is no `seo-remediation`
environment and no configured App/PAT remediation secret or App variables.

Pending setup: protected remediation environment
with reviewers, selected-repository GitHub App or fine-grained PAT, approved
metadata policies and client CI/deployment-trigger review. Dynamic framework
adapters and arbitrary client application test orchestration are not implemented.
No enabled policy exists and no client source repository has been changed.

## Minimal owner actions

1. No GSC permission action remains: all 13 properties were verified with
   `siteFullUser` access in audit 41026334512. The earlier denials are historical.
2. Review PR #6 and then the dependent platform PR; normal review/merge is required
   before the Monday schedule uses the new implementation.
3. Confirm the intended CardBros domain relationship before a canonical fix.
   Photography and Tvari Kirpeja source repositories are now owner-confirmed;
   any enabled fix policy still requires a reviewed source commit and deployment-trigger review.
4. If enabling supported metadata proposals, configure the protected
   `seo-remediation` environment and scoped App/PAT described in setup docs,
   then review explicit target-file policies. Keep deployment triggers disabled
   for proposal branches.

## Follow-up hardening

PR #7 now also checks HTTP Link canonical declarations, compares normalized HTML
and header targets, ignores misplaced body metadata, and marks truncated robots
and sitemap evaluations partial. Regression tests cover each case. Monitoring
artifacts now include a separate `access-actions.md` and matching JSON checklist
with the exact denied property and public service-account identity. No permission
change is performed by generating those artifacts.

On 30 October 2026 the owner confirmed `tvarikirpeja.lt` maps to
`elieassaf33/ainos_plauku` (`main`) and `alisosfotografija.lt` maps to
`elieassaf33/alisos_foto_django` (`master`). Both registry entries are now
`confirmed_by_owner`, without enabling remediation or changing GSC access.

## Latest live permission verification

[Audit 41026334512](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41026334512)
verified the identity `intech-seo-autopilot@intech-seo-autopilot.iam.gserviceaccount.com`
with `siteFullUser` access on all 13 properties. Every URL Inspection request
succeeded. Seven properties returned traffic data; Tesla EU and the five additions
returned authorized no-data. All 13 technical audits completed and the health gate
passed. Downloaded artifacts confirm `unhealthy_properties: []`,
`permission_actions: []` and `other_unverified_properties: []`.
This supersedes the earlier permission-denial blockers; no permissions were
changed by repository code or this agent.
