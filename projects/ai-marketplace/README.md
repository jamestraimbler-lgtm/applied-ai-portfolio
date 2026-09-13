# AI marketplace — prototype case study

A marketplace for listing AI tools or MCP servers and subscribing to them.
Original source was inspected on September 13; retained commits span June
16–20, 2026. This repository contains the case study, not the full application.

## What exists

- Next.js, React and strict TypeScript with tRPC procedures.
- Shared Zod schemas and Prisma/PostgreSQL models and migrations.
- Public, authenticated, seller and administrator procedure tiers.
- Supabase session verification and application-user mapping.
- Listing ownership checks and transactional review/rating updates.
- Stripe Checkout creation and signed webhook parsing.
- MCP capability probing, access-key handling and gateway authorization.

The listing evaluator is a deterministic rules-based stub, not an LLM agent.

## A design choice to discuss

The review procedure writes the review and recomputes its aggregate rating
inside a transaction. This shortened source excerpt shows the aggregate update:

```typescript
const agg = await tx.review.aggregate({
  where: { listingId: input.listingId, deletedAt: null },
  _avg: { rating: true },
  _count: { rating: true },
});
const updated = await tx.listing.update({
  where: { id: input.listingId },
  data: {
    ratingAvg: agg._avg.rating ?? 0,
    ratingCount: agg._count.rating,
  },
  select: { ratingAvg: true, ratingCount: true },
});
```

Source: `ai-marketplace/src/server/api/routers/review.ts`, inside `upsert`.
This is an excerpt, not a standalone example or proof of concurrent behavior.

## Exact unfinished paths

| Area | Present in source | Remaining boundary |
| --- | --- | --- |
| Authentication | Supabase verification and user mapping | Deployed session/access testing not performed here |
| Billing | Checkout and webhook handlers | Cancellation updates a local flag without calling Stripe |
| Webhooks | Signature validation and subscription updates | Checkout handler increments a count on each delivery; repeat-delivery safety needs a fix and test |
| MCP gateway | Key validation and listing matching | Returns authorization JSON; does not forward to the MCP server |
| Listing evaluator | Structured rules-based verdict | No model evaluation or benchmark |
| Buyer reviews | Subscription presence affects verified status | Others can review with written text; subscription presence alone does not prove payment |

The previous summary called auth and Checkout unwired. The source supports
this more precise description, while still leaving the product unfinished.

## End of track

**Documented application prototype.** No hosted availability, successful
payment, security certification or customer adoption is claimed. No service
or database was contacted in this audit. A scoped return would finish one
sandbox workflow and its cancellation, repeat-event and access tests.
[Project register](../../docs/project-status.md).
