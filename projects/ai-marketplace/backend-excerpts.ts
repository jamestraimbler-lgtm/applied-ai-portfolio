/**
 * AI marketplace: selected original implementation excerpts.
 * Reviewed 14 September 2026; source commit 1ce28f9.
 * Non-standalone reading sample: imports, schemas, context and router wrappers
 * are intentionally absent. This file is not built or covered by portfolio tests.
 * Selected source ranges below are copied verbatim, including their comments.
 * They contain no credentials, private service URLs or customer records.
 */

// Authenticated, seller and administrator access
// Original: src/server/api/trpc.ts, lines 47-77.
export const protectedProcedure = t.procedure.use(({ ctx, next }) => {
  if (!ctx.user) {
    throw new TRPCError({ code: "UNAUTHORIZED", message: "You must be signed in." });
  }
  return next({ ctx: { ...ctx, user: ctx.user } });
});

/**
 * Requires a signed-in user who is also a seller. Loads the SellerProfile once
 * and puts it on the context so resolvers don't re-query it.
 */
export const sellerProcedure = protectedProcedure.use(async ({ ctx, next }) => {
  const seller = await ctx.db.sellerProfile.findFirst({
    where: { userId: ctx.user.id, deletedAt: null },
  });
  if (!seller) {
    throw new TRPCError({
      code: "FORBIDDEN",
      message: "You need a seller profile to do this.",
    });
  }
  return next({ ctx: { ...ctx, seller } });
});

/** Requires platform admin. */
export const adminProcedure = protectedProcedure.use(({ ctx, next }) => {
  if (!ctx.user.isAdmin) {
    throw new TRPCError({ code: "FORBIDDEN", message: "Admins only." });
  }
  return next({ ctx });
});

// Validated intake and related records in one transaction
// Original: src/server/api/routers/listing.ts, lines 182-235.
  create: sellerProcedure
    .input(createListingSchema)
    .mutation(async ({ ctx, input }) => {
      const { mcpSpec, plans, categoryIds, ...listingData } = input;

      // Generate a unique slug from the name.
      const baseSlug = slugify(listingData.name);
      const slug = await ensureUniqueSlug(ctx.db, baseSlug);

      // Everything in one transaction: if any part fails, nothing is written.
      return ctx.db.$transaction(async (tx) => {
        const listing = await tx.listing.create({
          data: {
            ...listingData,
            slug,
            sellerId: ctx.seller.id,
            status: "DRAFT",
            mcpSpec: {
              create: {
                transport: mcpSpec.transport,
                endpointUrl: mcpSpec.endpointUrl,
                authType: mcpSpec.authType,
                // Zod already validated this shape; store as JSON.
                capabilities: mcpSpec.capabilities,
                protocolVersion: mcpSpec.protocolVersion,
              },
            },
            plans: {
              create: plans.map((p) => ({
                name: p.name,
                model: p.model,
                priceCents: p.priceCents,
                currency: p.currency,
                interval: p.interval,
                unitPriceCents: p.unitPriceCents,
                unitLabel: p.unitLabel,
              })),
            },
            ...(categoryIds.length
              ? {
                  categories: {
                    create: categoryIds.map((categoryId, i) => ({
                      categoryId,
                      isPrimary: i === 0,
                    })),
                  },
                }
              : {}),
          },
          include: { mcpSpec: true, plans: true },
        });
        return listing;
      });
    }),

// Pending escalations visible to an administrator
// Original: src/server/api/routers/admin.ts, lines 21-49.
  escalationQueue: adminProcedure.query(async ({ ctx }) => {
    const listings = await ctx.db.listing.findMany({
      where: { status: "IN_REVIEW", deletedAt: null },
      orderBy: { updatedAt: "asc" }, // oldest waiting first
      select: {
        id: true,
        name: true,
        tagline: true,
        updatedAt: true,
        seller: { select: { handle: true, displayName: true } },
        listingReviews: {
          orderBy: { createdAt: "desc" },
          take: 1,
          select: { verdict: true, riskScore: true, createdAt: true },
        },
      },
    });
    // Keep only those whose latest review is an escalation.
    return listings
      .filter((l) => l.listingReviews?.[0]?.verdict === "ESCALATED")
      .map((l) => ({
        id: l.id,
        name: l.name,
        tagline: l.tagline,
        waitingSince: l.updatedAt,
        seller: l.seller,
        riskScore: l.listingReviews?.[0]?.riskScore ?? null,
      }));
  }),

// A human decision recorded with its resulting state
// Original: src/server/api/routers/admin.ts, lines 73-115.
  resolve: adminProcedure
    .input(
      z.object({
        id: z.string().cuid(),
        decision: z.enum(["APPROVED", "REJECTED"]),
        note: z.string().max(2000).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const listing = await ctx.db.listing.findFirst({
        where: { id: input.id, status: "IN_REVIEW", deletedAt: null },
        select: { id: true },
      });
      if (!listing) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: "This listing isn't awaiting review.",
        });
      }

      await ctx.db.$transaction(async (tx) => {
        // Record the human decision as a new review row (audit trail).
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

      return { ok: true, decision: input.decision };
    }),
