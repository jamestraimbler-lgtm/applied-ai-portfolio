# Source publication — 16 September 2026

## Addition on 13 October 2026

Added FinanZen CRM/document-review source, selected membership-backend source
and tests, and Lost Temple logic modules/tests. Original runtime records,
customer documents, environment/configuration files, website books/artwork and
private histories are excluded. FinanZen's new synthetic harness redirects
all data paths before importing the app and mocks inference. Its numeric
fixtures contain generated scenarios rather than customer records.

The membership snapshot is selected review material, not a runnable copy of
the original website. Lost Temple includes runnable round/progression tests.
The [refreshed verification](verification-2026-10-13.md) records results and
limits. The whole portfolio passed a redacted Gitleaks directory scan before
publication; no credential findings were reported. This is a credential check,
not a security or privacy certification.

## Earlier edition

This edition makes the substantial projects reviewable in one repository.
The source was copied into a fresh checkout of the existing public portfolio;
private project histories and runtime data were not imported.

| Project | Origin and included scope | Deliberate exclusions / changes |
| --- | --- | --- |
| AImazon | Local application's `src`, Prisma schema/migrations, architecture note, package lock and build configuration | Private environment, node_modules, generated builds, administrative scripts and private Git history omitted. New setup README and dummy environment example; authorization comment corrected |
| Brain | 50 Python files from archived root and source-adapter directory | Logs, predictions, account files and scheduler scripts omitted. Machine-specific alert path made configurable; personal chat prompt replaced with neutral research context |
| Mac Agent | All four archived Python modules | Memory database, briefings and scheduler configuration omitted. Added configurable database path and temporary-database walkthrough |
| Veggie Kitchen | 14 archived Python modules and historical requirements | Account files and bulk generated media omitted. Existing preview retained; archived experiments labeled |
| CatalogCue / quality gate | Existing public source, demonstrations and tests | Preserved as runnable samples |

The broader local survey covered project repositories, the named archive
directory and marketplace development drops. Development drops are earlier
pieces of AImazon, not separate completed projects. Smaller model-client
experiments and the trading-research generations remain in the project register
with appropriate status; they are not promoted as independent finished products.

Code volume is a measure of source scope, not a score for quality, experience or
hours worked. Retained dated outputs are not uptime proof. Historical research
prompts, market examples and conclusions in archived source have not been
revalidated as current facts. Source snapshots may contain old assumptions and
overlapping experiments; the featured runnable examples have narrower checks.

Publication checks include a credential scan and review for personal paths,
embedded account context and runtime exports. No scan establishes a security
certification. The included application remains a prototype with documented
limitations. Nothing in this publication starts a service or changes a live,
paper or research execution mode.

[Portfolio](../README.md)
