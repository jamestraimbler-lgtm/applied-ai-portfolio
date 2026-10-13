# Membership backend access and payment handling

A Node.js membership-site rebuild, developed with substantial AI assistance.
It connects account sessions, paid-content access, subscription events and
persistent storage. The backend is tested locally; live payments and email
delivery are not connected and no membership production rollout is claimed.

## Inspect the engineering

- [Session and request controls](source/security.js): salted scrypt passwords,
  opaque sessions stored by hash, session rotation, CSRF/origin checks and
  persistent rate limits.
- [Billing](source/billing.js): signed Stripe events, repeated-event handling,
  reconciliation against current subscription state and retriable failures.
- [Schema](source/schema.js) and [Cloudflare adapter](source/cloudflare/database.js):
  shared SQL storage behavior through a Durable Object transaction boundary.
- [Node integration tests](tests/app.test.js) and
  [Worker integration tests](tests/cloudflare/worker.test.js): access denied on
  direct URLs, download and search paths; expired/single-use tokens; event
  retries; state preserved across a runtime restart.

All 24 integration tests passed in the original project on 13 October 2026,
after rebuilding the Worker. The Worker tests use an actual local Miniflare
runtime with persistent SQL/R2 storage and intercepted Stripe/mail endpoints.
They do not establish successful real charges or delivered email.

This portfolio includes selected source and test files for review, not the
whole website or a runnable install. The tests depend on omitted application,
content, template and build modules. Site artwork, books, paid content,
environment settings and runtime data are excluded. A walkthrough of the
original project can demonstrate the complete local suite.

## A useful interview walkthrough

Trace a duplicate webhook, an unavailable payment API and a runtime restart.
Explain how the stored subscription state determines access and why receiving
an event alone does not prove that a member should retain access.

[Portfolio](../../README.md).
