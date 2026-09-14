# AImazon — a marketplace for AI agents

AImazon is my marketplace concept for individuals and businesses to discover
AI agents, and for creators to list them. "Amazon for AI" is how I describe
the idea: bringing discovery and the supporting platform into one place.

**Endpoint: documented application prototype.** The project connects accounts,
structured submissions, review decisions and external service events. It is
my strongest case study for the breadth involved in building a practical
application. This repository contains the case study and short source excerpts;
the full application remains separate.

Original source at commit `1ce28f9` was inspected on 13–14 September 2026.
Retained commits span 16–20 June 2026. The implementation was substantially
AI-assisted; [how I work](../../docs/how-i-work.md) describes that collaboration.

## The problem

The intended users have two sides: people or businesses looking for an AI
agent, and creators who want to list their work. The inspected prototype
implements parts of the platform behind that idea, including listings for
AI tools and MCP servers. The product vision is broader than the completed
implementation.

That marketplace needs a workflow behind its pages.
A seller should create a structured listing, submit it for review and understand
the decision. Reviewers need the relevant context, and application records
need to reflect events from external services.

## What I built with AI assistance

| Workflow need | Implemented in source | Why it matters |
| --- | --- | --- |
| Know who is acting | Supabase session verification and application-user mapping; public, signed-in, seller and administrator procedure tiers | Establishes a shared identity and access boundary for requests |
| Collect consistent submissions | Zod input validation; listing, MCP specification, plans and category relations written in a database transaction | Keeps related intake records together and rejects invalid shapes |
| Apply ownership rules | Seller-scoped listing reads and updates | An authenticated account alone does not grant access to another seller's draft |
| Route a submission for review | Draft and review states; structured verdict, reasoning and flags; approval, rejection or escalation | Makes the decision and its next step explicit |
| Allow a human decision | Administrator escalation queue, review details and transactional resolution | Preserves the automated assessment and adds a separate human decision record |
| Reflect external events | Stripe Checkout creation, signed webhook parsing and subscription/account updates | Connects external service events to application state |
| Explore access to AI tools | MCP capability probing, access-key validation and gateway authorization | Demonstrates the integration boundary; forwarding is still unfinished |

The web stack is Next.js, React, TypeScript, tRPC, Prisma and PostgreSQL.
The listing evaluator is a **deterministic rules-based stub**. Its review
workflow is not evidence of an advanced AI safety system or a model that
reliably judges tool safety.

## One workflow to walk through

1. A seller signs in; the request context maps the verified session to an
   application user, and seller middleware resolves their seller profile.
2. Creating a listing validates the submission and writes its related records
   together in a transaction with initial status `DRAFT`.
3. Submitting for review checks ownership and allowed status, records the review
   and calls the probe and rules-based evaluator.
4. The verdict is saved and routes the listing to publication, rejection or
   continued review. An escalation becomes visible in the administrator queue.
5. A human resolution creates a separate review record and changes listing
   status in a transaction.

This describes the inspected implementation. The complete user journey was
not executed in this portfolio audit.

## Source details

[Read the selected backend implementation](backend-excerpts.ts): access
middleware, transactional listing creation, the escalation queue and human
resolution. Each section records its original file and line range. It is a
non-standalone reading sample, outside the Python examples' test coverage.

### Keeping a human decision with its result

This shortened excerpt comes from `src/server/api/routers/admin.ts`, inside
`resolve`, after administrator access and pending-state checks. The surrounding router and one source comment are omitted for clarity.

```typescript
await ctx.db.$transaction(async (tx) => {
  await tx.listingReview.create({
    data: {
      listingId: listing.id,
      verdict: input.decision,
      reviewedBy: "HUMAN",
      reasoning: input.note ?? `Resolved by admin: ${input.decision}.`,
      resolvedAt: new Date(),
    },
  });

  await tx.listing.update({
    where: { id: listing.id },
    data:
      input.decision === "APPROVED"
        ? { status: "PUBLISHED", publishedAt: new Date() }
        : { status: "REJECTED" },
  });
});
```

The transaction groups the decision record and resulting status change.
It does not by itself prove correct concurrent behavior or complete access
security; those need focused tests and a full workflow review.

## How this transfers to other work

Web products, business automation and internal tools share several needs:
structured intake, permissions, review queues, human decisions and records
that stay in sync. This project gives me practical experience working with
those components and connecting them across an application.

Taking the prototype further would add feedback from users, a complete
tested journey and operational experience. Those are concrete next steps
for product work in a team.

## Exact unfinished paths

| Area | Present in source | Remaining boundary |
| --- | --- | --- |
| Authentication and review | Session resolution, access rules, submission states and human resolution | Deployed access and complete workflow testing not performed here |
| Billing | Checkout and webhook handlers | Cancellation updates a local flag without calling Stripe |
| Webhooks | Signature validation and subscription updates | Checkout handler increments a count on each delivery; repeat-delivery safety needs a fix and test |
| MCP gateway | Key validation and listing matching | Returns authorization JSON; does not forward to the MCP server |
| Listing evaluator | Structured rules-based verdict | No model evaluation or benchmark; verdicts are not a safety guarantee |
| Buyer reviews | Review and aggregate rating updated transactionally | Subscription presence affects verified status but does not prove payment |

## End of track

**A substantial backend and application prototype, documented for review.**
The next useful milestone would complete one sandbox user journey and its
cancellation, repeated-event and access checks. No hosted availability,
successful payment, security certification or customer adoption is claimed.
No service or database was contacted in this audit.

[Project register](../../docs/project-status.md) · [Skills map](../../docs/skills-and-next-steps.md) · [Portfolio](../../README.en.md)
