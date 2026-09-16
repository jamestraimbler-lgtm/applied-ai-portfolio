# Data Model — Design Decisions

The schema lives in `prisma/schema.prisma`. This doc explains the *why* behind
the non-obvious calls so nobody accidentally undoes a deliberate decision.

## The one-line summary

A **Listing** is one MCP server. Sellers (`SellerProfile`) own listings, buyers
(`User`) subscribe to them under a `PricingPlan`, and `Stripe Connect` moves the
money while the platform takes a cut. `McpSpec` holds the technical contract
that makes one-click connect possible.

---

## Decisions that matter

### 1. Money is integer cents, never a float
Every price is `Int` minor units (`1999` = $19.99) plus a `currency` string.
Floats lose precision (`0.1 + 0.2 != 0.3`), and that precision loss compounds
into real accounting bugs. This is non-negotiable and matches how Stripe itself
represents amounts. If you ever see a `Float` used for money in this codebase,
it's a bug.

### 2. Buyer vs seller is NOT a role enum on User
A `User` can buy and sell at the same time. Modeling "role" as a single field
forces awkward either/or logic. Instead:
- Anyone can be a buyer (just `User` + `Subscription` rows).
- Becoming a seller = getting a `SellerProfile` (1:1 with User).
- `isAdmin` is separate because that's a *platform* permission, not a
  marketplace identity.

### 3. Listing and McpSpec are split 1:1
`Listing` is about **commerce and discovery** (name, tagline, rating, status).
`McpSpec` is about **how to technically connect** (transport, endpoint, auth,
capabilities). Keeping them separate means the catalog query stays lean and the
technical spec can evolve without bloating every listing read.

### 4. Soft-delete (`deletedAt`) on user-created rows
We never hard-delete listings, reviews, sellers, or users. Reasons: you can't
restore trust history (reviews, ratings, transaction records) once it's gone,
and hard-deletes break foreign-key references on past subscriptions. Filter
`deletedAt IS NULL` in queries; the data stays for audit/recovery.

### 5. Denormalized aggregates on Listing
`ratingAvg`, `ratingCount`, `activeSubCount` are stored on the row, not computed
on every catalog render. They're kept correct by writing them *in the same
transaction* that creates a `Review` or `Subscription`. Tradeoff: a little write
complexity in exchange for a catalog that doesn't melt under read load. This is
the standard marketplace pattern.

### 6. We mirror Stripe state, but Stripe is the source of truth
`payoutStatus`, `SubscriptionStatus`, `currentPeriodEnd`, `stripePriceId`, etc.
are *mirrors* refreshed via Stripe webhooks. We store them so the app can gate
access (e.g. "is this sub active?") without an API round-trip on every request.
But for anything billing-critical, Stripe wins. The mirror can lag; design for
that (webhooks reconcile it).

### 7. Credentials are never stored in plaintext
`Subscription.accessKeyCipher` holds an **encrypted** access key (or a reference
to one in a secrets manager) — never the raw key. Same for anything sensitive.
Plaintext secrets in a DB is the kind of thing that ends companies.

### 8. Usage events are append-only with an idempotency flag
`UsageEvent` rows are never mutated. `reportedToStripe` guards against
double-billing when we batch-report metered usage. Append-only + idempotency is
how you keep metered billing from charging people twice.

### 9. Explicit join tables, not implicit m:n
`CategoriesOnListings` is a real table (with `isPrimary`, `assignedAt`) rather
than Prisma's implicit many-to-many. This lets us add per-assignment metadata
later without a painful migration. Same reasoning would apply to any future
tagging relationship.

### 10. Public URLs use `slug`/`handle`/`cuid`, never sequential ints
Listings have `slug`, sellers have `handle`, ids are `cuid`. We never expose
auto-incrementing integers in URLs — they leak how many rows exist and let
people enumerate your catalog/users. (This schema uses `cuid` ids throughout,
so there are no sequential ints to leak anyway.)

---

## Enums at a glance

- `PayoutStatus`: NOT_STARTED → PENDING → ACTIVE (or RESTRICTED)
- `ListingStatus`: DRAFT → IN_REVIEW → PUBLISHED (or SUSPENDED / ARCHIVED)
- `McpTransport`: STDIO | SSE | STREAMABLE_HTTP
- `McpAuthType`: NONE | API_KEY | OAUTH
- `PricingModel`: FREE | FLAT_RATE | USAGE
- `BillingInterval`: MONTH | YEAR
- `SubscriptionStatus`: INCOMPLETE → ACTIVE → (PAST_DUE / CANCELED / PAUSED)

---

## Rules enforced at the app layer (not the DB)

Some invariants can't be expressed as DB constraints and must be enforced in
code (this is where Zod + your service layer come in):

- A review can only be written by someone with a (current or past)
  subscription to that listing.
- A buyer can have only ONE *active* subscription per listing (canceled rows for
  the same pair are allowed to coexist as history).
- `rating` must be 1–5.
- `McpSpec.capabilities` JSON must match the expected shape before it's written.

---

## What's intentionally NOT here yet (v1 scope)

These are real future needs, deliberately deferred so v1 stays solid and small:

- **Refunds / disputes / payout ledger** — comes with deeper Stripe Connect work.
- **Versioning of MCP specs** — when sellers ship breaking changes to their
  server, we'll want version history. Not v1.
- **Teams / orgs** — buyers are individuals for now.
- **Full-text search infra** — start with Postgres FTS, add Typesense/Meilisearch
  when scale demands it.
- **Webhook event log table** — for replaying/debugging Stripe webhooks. Add
  when wiring up billing.
