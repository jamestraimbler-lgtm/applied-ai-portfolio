/**
 * Listing router.
 *
 * Public: browse the catalog (cursor-paginated, filtered) and view a listing.
 * Seller: create / update / publish / archive their own listings.
 *
 * Key patterns demonstrated here:
 *  - Cursor pagination for a catalog that grows without bound.
 *  - Transactional creation: a Listing + its McpSpec + its PricingPlans are
 *    written atomically, so a listing is never half-built.
 *  - Ownership enforcement: a seller can only touch their own listings.
 *  - Slug generation with collision handling.
 */
import { TRPCError } from "@trpc/server";
import {
  catalogQuerySchema,
  createListingSchema,
  listingSlugSchema,
  listingIdSchema,
  updateListingSchema,
} from "@/schemas";
import {
  createTRPCRouter,
  publicProcedure,
  sellerProcedure,
} from "@/server/api/trpc";
import { slugify, ensureUniqueSlug } from "@/lib/slug";
import { evaluateListing } from "@/server/agent/reviewer";
import { probeListing } from "@/server/agent/prober";

const CARD_SELECT = {
  id: true,
  slug: true,
  name: true,
  tagline: true,
  iconUrl: true,
  ratingAvg: true,
  ratingCount: true,
  activeSubCount: true,
  seller: { select: { handle: true, displayName: true } },
  mcpSpec: { select: { transport: true, authType: true, capabilities: true } },
  plans: {
    where: { isActive: true },
    select: { model: true, priceCents: true, currency: true, interval: true, unitPriceCents: true, unitLabel: true },
  },
} as const;

export const listingRouter = createTRPCRouter({
  // -------------------------------------------------------------------------
  //  PUBLIC: featured listing
  // -------------------------------------------------------------------------
  featured: publicProcedure.query(async ({ ctx }) => {
    return ctx.db.listing.findFirst({
      where: { status: "PUBLISHED", deletedAt: null, isFeatured: true },
      select: CARD_SELECT,
    });
  }),

  // -------------------------------------------------------------------------
  //  PUBLIC: hero stats
  // -------------------------------------------------------------------------
  stats: publicProcedure.query(async ({ ctx }) => {
    const [agentCount, categoryRows] = await Promise.all([
      ctx.db.listing.count({ where: { status: "PUBLISHED", deletedAt: null } }),
      ctx.db.categoriesOnListings.findMany({
        where: { listing: { status: "PUBLISHED", deletedAt: null } },
        select: { categoryId: true },
        distinct: ["categoryId"],
      }),
    ]);
    return { agentCount, categoryCount: categoryRows.length };
  }),

  // -------------------------------------------------------------------------
  //  PUBLIC: categories with published listings (for filter pills)
  // -------------------------------------------------------------------------
  categories: publicProcedure.query(async ({ ctx }) => {
    const cats = await ctx.db.category.findMany({
      where: {
        listings: { some: { listing: { status: "PUBLISHED", deletedAt: null } } },
      },
      select: { slug: true, name: true },
      orderBy: { name: "asc" },
    });
    return cats;
  }),

  // -------------------------------------------------------------------------
  //  PUBLIC: browse the catalog
  // -------------------------------------------------------------------------
  list: publicProcedure
    .input(catalogQuerySchema)
    .query(async ({ ctx, input }) => {
      const { search, categorySlug, price, sort, cursor, limit } = input;

      const orderBy =
        sort === "newest"
          ? { publishedAt: "desc" as const }
          : sort === "most_popular"
            ? { activeSubCount: "desc" as const }
            : { ratingAvg: "desc" as const };

      const items = await ctx.db.listing.findMany({
        // Fetch one extra row to know whether there's a next page.
        take: limit + 1,
        ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
        where: {
          status: "PUBLISHED",
          deletedAt: null,
          ...(search
            ? {
                OR: [
                  { name: { contains: search, mode: "insensitive" } },
                  { tagline: { contains: search, mode: "insensitive" } },
                ],
              }
            : {}),
          ...(categorySlug
            ? { categories: { some: { category: { slug: categorySlug } } } }
            : {}),
          ...(price === "free"
            ? { plans: { some: { isActive: true, model: "FREE" } } }
            : price === "paid"
              ? {
                  plans: { some: { isActive: true, model: { not: "FREE" } } },
                  NOT: { plans: { some: { isActive: true, model: "FREE" } } },
                }
              : {}),
        },
        orderBy,
        select: CARD_SELECT,
      });

      let nextCursor: string | undefined;
      if (items.length > limit) {
        // The extra row is the start of the next page.
        const next = items.pop();
        nextCursor = next?.id;
      }

      return { items, nextCursor };
    }),

  // -------------------------------------------------------------------------
  //  PUBLIC: view a single listing by slug
  // -------------------------------------------------------------------------
  bySlug: publicProcedure
    .input(listingSlugSchema)
    .query(async ({ ctx, input }) => {
      const listing = await ctx.db.listing.findFirst({
        where: { slug: input.slug, deletedAt: null },
        include: {
          seller: { select: { handle: true, displayName: true, bio: true } },
          mcpSpec: true,
          plans: { where: { isActive: true } },
          categories: { include: { category: true } },
        },
      });

      // Only PUBLISHED listings are visible to the public. (A seller viewing
      // their own draft should use the seller-scoped `byId` instead.)
      if (!listing || listing.status !== "PUBLISHED") {
        throw new TRPCError({ code: "NOT_FOUND", message: "Listing not found." });
      }
      return listing;
    }),

  // -------------------------------------------------------------------------
  //  SELLER: list my own listings (any status)
  // -------------------------------------------------------------------------
  mine: sellerProcedure.query(async ({ ctx }) => {
    return ctx.db.listing.findMany({
      where: { sellerId: ctx.seller.id, deletedAt: null },
      orderBy: { updatedAt: "desc" },
      include: { plans: { where: { isActive: true } }, mcpSpec: true },
    });
  }),

  // -------------------------------------------------------------------------
  //  SELLER: create a listing (+ spec + plans) atomically
  // -------------------------------------------------------------------------
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

  // -------------------------------------------------------------------------
  //  SELLER: load one of their own listings by id (any status, for editing)
  // -------------------------------------------------------------------------
  byId: sellerProcedure
    .input(listingIdSchema)
    .query(async ({ ctx, input }) => {
      const listing = await ctx.db.listing.findFirst({
        where: { id: input.id, sellerId: ctx.seller.id, deletedAt: null },
        include: {
          mcpSpec: true,
          plans: { where: { isActive: true } },
          categories: { include: { category: true } },
        },
      });
      if (!listing) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Listing not found." });
      }
      return listing;
    }),

  // -------------------------------------------------------------------------
  //  SELLER: update listing metadata (ownership enforced)
  // -------------------------------------------------------------------------
  update: sellerProcedure
    .input(updateListingSchema)
    .mutation(async ({ ctx, input }) => {
      const { id, categoryIds, mcpSpec, plans, ...data } = input;

      // Load the listing to confirm ownership and check current status.
      const existing = await ctx.db.listing.findFirst({
        where: { id, sellerId: ctx.seller.id, deletedAt: null },
        select: { id: true, status: true },
      });
      if (!existing) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Listing not found." });
      }

      // Editing a PUBLISHED or REJECTED listing forces it back to DRAFT so it
      // must go through review again (prevents bait-and-switch).
      const needsReReview =
        existing.status === "PUBLISHED" || existing.status === "REJECTED";

      await ctx.db.$transaction(async (tx) => {
        // Update text fields + status transition.
        await tx.listing.update({
          where: { id },
          data: {
            ...data,
            ...(needsReReview ? { status: "DRAFT" } : {}),
          },
        });

        // Update MCP spec if provided.
        if (mcpSpec) {
          await tx.mcpSpec.upsert({
            where: { listingId: id },
            update: {
              transport: mcpSpec.transport,
              endpointUrl: mcpSpec.endpointUrl,
              authType: mcpSpec.authType,
              capabilities: mcpSpec.capabilities,
              protocolVersion: mcpSpec.protocolVersion,
            },
            create: {
              listingId: id,
              transport: mcpSpec.transport,
              endpointUrl: mcpSpec.endpointUrl,
              authType: mcpSpec.authType,
              capabilities: mcpSpec.capabilities,
              protocolVersion: mcpSpec.protocolVersion,
            },
          });
        }

        // Replace pricing plans if provided.
        if (plans) {
          // Deactivate old plans, then create new ones.
          await tx.pricingPlan.updateMany({
            where: { listingId: id },
            data: { isActive: false },
          });
          for (const p of plans) {
            await tx.pricingPlan.create({
              data: {
                listingId: id,
                name: p.name,
                model: p.model,
                priceCents: p.priceCents,
                currency: p.currency,
                interval: p.interval,
                unitPriceCents: p.unitPriceCents,
                unitLabel: p.unitLabel,
              },
            });
          }
        }

        // Replace categories if provided.
        if (categoryIds) {
          await tx.categoriesOnListings.deleteMany({ where: { listingId: id } });
          if (categoryIds.length > 0) {
            await tx.categoriesOnListings.createMany({
              data: categoryIds.map((categoryId, i) => ({
                listingId: id,
                categoryId,
                isPrimary: i === 0,
              })),
            });
          }
        }
      });

      const updated = await ctx.db.listing.findUniqueOrThrow({
        where: { id },
        include: { mcpSpec: true, plans: { where: { isActive: true } }, categories: { include: { category: true } } },
      });

      return { listing: updated, statusChanged: needsReReview };
    }),

  // -------------------------------------------------------------------------
  //  SELLER: submit a draft for review (the trust gate before going live)
  // -------------------------------------------------------------------------
  // SELLER: the most recent review verdict for one of their listings (so they
  // can see WHY it was rejected/escalated and what to fix).
  latestReview: sellerProcedure
    .input(listingIdSchema)
    .query(async ({ ctx, input }) => {
      // Confirm ownership before exposing review details.
      const owned = await ctx.db.listing.findFirst({
        where: { id: input.id, sellerId: ctx.seller.id, deletedAt: null },
        select: { id: true },
      });
      if (!owned) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Listing not found." });
      }
      return ctx.db.listingReview.findFirst({
        where: { listingId: input.id },
        orderBy: { createdAt: "desc" },
        select: {
          verdict: true,
          reasoning: true,
          riskFlags: true,
          riskScore: true,
          reviewedBy: true,
          createdAt: true,
        },
      });
    }),

  // SELLER: submit a listing for review. Runs the approval agent synchronously
  // and routes the verdict. EVERY listing goes through this — onboarding's first
  // listing and every later one — and the ONLY way a listing reaches PUBLISHED
  // is an APPROVED verdict here. There is no manual-publish path.
  submitForReview: sellerProcedure
    .input(listingIdSchema)
    .mutation(async ({ ctx, input }) => {
      // Load the listing (must be the seller's own, and in a submittable state).
      const listing = await ctx.db.listing.findFirst({
        where: {
          id: input.id,
          sellerId: ctx.seller.id,
          deletedAt: null,
          // Only DRAFT or a previously REJECTED listing can be (re)submitted.
          status: { in: ["DRAFT", "REJECTED"] },
        },
        include: {
          mcpSpec: true,
          plans: { where: { isActive: true } },
        },
      });
      if (!listing) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: "Only your own draft or rejected listings can be submitted.",
        });
      }

      // Move to IN_REVIEW and create the PENDING review record up front, so the
      // state is correct even if evaluation throws.
      await ctx.db.listing.update({
        where: { id: listing.id },
        data: { status: "IN_REVIEW" },
      });
      const reviewRow = await ctx.db.listingReview.create({
        data: { listingId: listing.id, verdict: "PENDING", reviewedBy: "AGENT" },
      });

      // Probe the MCP endpoint for real capability verification.
      const probeResult = listing.mcpSpec
        ? await probeListing({
            transport: listing.mcpSpec.transport,
            endpointUrl: listing.mcpSpec.endpointUrl,
            authType: listing.mcpSpec.authType,
            capabilities: listing.mcpSpec.capabilities,
          })
        : null;

      // Run the approval agent.
      const { verdict, modelId } = await evaluateListing({
        name: listing.name,
        tagline: listing.tagline,
        description: listing.description,
        pricing: (listing.plans ?? []).map((p) => ({
          model: p.model,
          priceCents: p.priceCents,
          unitPriceCents: p.unitPriceCents,
        })),
        mcpSpec: listing.mcpSpec
          ? {
              transport: listing.mcpSpec.transport,
              endpointUrl: listing.mcpSpec.endpointUrl,
              authType: listing.mcpSpec.authType,
              capabilities: listing.mcpSpec.capabilities,
            }
          : null,
      }, probeResult);

      // Persist the verdict + route the listing status, atomically. The mapping:
      //   APPROVED  -> listing PUBLISHED (the ONLY publish path)
      //   REJECTED  -> listing REJECTED (seller revises + resubmits)
      //   ESCALATED -> listing stays IN_REVIEW, awaits a human
      await ctx.db.$transaction(async (tx) => {
        await tx.listingReview.update({
          where: { id: reviewRow.id },
          data: {
            verdict: verdict.verdict,
            reasoning: verdict.reasoning,
            riskFlags: verdict.riskFlags,
            riskScore: verdict.riskScore,
            modelId,
            probeResult: probeResult ?? undefined,
          },
        });

        if (verdict.verdict === "APPROVED") {
          await tx.listing.update({
            where: { id: listing.id },
            data: { status: "PUBLISHED", publishedAt: new Date() },
          });
        } else if (verdict.verdict === "REJECTED") {
          await tx.listing.update({
            where: { id: listing.id },
            data: { status: "REJECTED" },
          });
        }
        // ESCALATED: leave the listing IN_REVIEW; nothing else to change.
      });

      return {
        verdict: verdict.verdict,
        reasoning: verdict.reasoning,
        riskScore: verdict.riskScore,
      };
    }),

  // -------------------------------------------------------------------------
  //  SELLER: archive a listing (soft retire; existing subs continue)
  // -------------------------------------------------------------------------
  archive: sellerProcedure
    .input(listingIdSchema)
    .mutation(async ({ ctx, input }) => {
      const result = await ctx.db.listing.updateMany({
        where: { id: input.id, sellerId: ctx.seller.id, deletedAt: null },
        data: { status: "ARCHIVED" },
      });
      if (result.count === 0) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Listing not found." });
      }
      return { ok: true };
    }),
});
