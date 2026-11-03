# Verified metadata automation - 3 November 2026

Automatic free keyword discovery and title/meta-description updates are enabled
for all 13 registered properties. The metadata workflow follows a successful
Monday audit and uses the existing restricted SSH connection. The owner's PC is
not part of the schedule. No paid keyword or language-model API is used.

- [Main audit](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41610505385): passed, including GSC property health.
- [Chained production recovery](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41610876887): passed; all 11 client bundles healthy, with 35 public page checks.
- [Automatically triggered metadata workflow](https://github.com/elieassaf33/INTECH-SEO-Autopilot/actions/runs/41610876986): passed; all 13 properties processed, INTECH Europe published and verified, ten unchanged and two with no suitable keyword. No blocked results.

Earlier live checks also verified metadata publication for Alisos Fotografija,
Klaipedos Aliejus, CardBros, INTECH Lithuania, Tvari Kirpeja and Naturalus Maistas.
The shared CardBros template is written once and both domains are verified.
Complete receipts, source backups and the publication ledger remain under the
root-controlled `/var/lib/intech-seo-repairs/` directory.

Validation: 92 local tests, Python 3.12/3.14 GitHub CI, 41 server-relevant tests,
real Django inheritance checks for all ten VPS properties, and actionlint passed.
The template checks preserve other page paths, visible body copy and canonicals.

Netlify required re-uploading Google Reviews because its old bundle was no
longer cached. The replacement archive contains exactly the function source from
the deployed `commerce_well` commit `36a1a325f2fef9a766146befdbac6250b8a921aa`,
with its source entry and entire archive pinned by hash. Node.js 22, 1024 MB and
`us-east-2` remain unchanged. Every draft explicitly selects the original runtime,
even on a function-cache hit, and is verified before publication. Site environment
variables remain unchanged.

`SEO_METADATA_PUBLISH_ENABLED=true` is configured. The old paid content workflow
has been replaced. Visible text is not rewritten. Homepage-only policies apply
suitable broad topics supported by the site's current text; unsuitable suggestions
remain ideas and do not force changes. Source drift, API failures and failed live
checks are explicit failures, with rollback where a publication was attempted.
The installed metadata worker and all its dependencies/config are checked against
the tested GitHub version by the workflow. See [operation and limits](FREE-METADATA-AUTOMATION.md).
