# AImazon application source

The actual Next.js / TypeScript prototype: UI routes, tRPC API, Prisma schema
and migrations, Supabase sessions, Stripe integration and MCP access validation.
Copied from the retained application at commit `1ce28f9`, without its private
environment, local database state, operational scripts or Git history.

## Check the code without accounts

Requires Node.js 22 or newer and npm. From this directory:

```bash
npm ci --ignore-scripts
npm run db:generate
npm run typecheck
```

Prisma generation downloads a platform-specific engine if needed. No database
connection is required for these checks. See [verification](../../../docs/verification-2026-09-16.md)
for the actual checks performed on this snapshot.

## Explore locally

Copy `.env.example` to `.env` and configure a disposable PostgreSQL database,
Supabase development project and Stripe sandbox. Then:

```bash
npm run db:migrate
npm run dev
```

Database migrations change the configured database. The repository does not
provide production credentials or a hosted demo. Some flows remain incomplete;
in particular cancellation does not yet call Stripe, webhook counters need
repeat-delivery handling, and the gateway returns authorization JSON without
forwarding requests. The reviewer uses deterministic rules.

## Suggested review order

1. [Schema](prisma/schema.prisma) and [validation](src/schemas/index.ts).
2. [Session context](src/server/api/context.ts) and [procedure tiers](src/server/api/trpc.ts).
3. [Listing workflow](src/server/api/routers/listing.ts).
4. [Human review](src/server/api/routers/admin.ts).
5. [Subscription workflow](src/server/api/routers/subscription.ts) and [webhooks](src/app/api/webhooks/stripe/route.ts).
6. [Key validation](src/server/gateway/validate.ts) and [gateway route](src/app/api/gateway/%5Bslug%5D/route.ts).

Middleware provides runtime checks and narrowed types for procedures that use
it. Developers must still choose the correct procedure and scope each query.
Database transactions do not by themselves eliminate concurrency bugs.

[Case study and limitations](../README.md)
