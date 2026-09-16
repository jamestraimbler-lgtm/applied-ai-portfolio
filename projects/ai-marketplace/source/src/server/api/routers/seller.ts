/**
 * Seller router.
 *
 * Becoming a seller = creating a SellerProfile (1:1 with the user). Stripe
 * Connect onboarding is a separate step, kept as a clearly-marked integration
 * point — actually creating the connected account and the onboarding link is
 * Stripe-side work to wire when you add billing.
 */
import { z } from "zod";
import { TRPCError } from "@trpc/server";
import {
  handleSchema,
  onboardingWithListingSchema,
  updateSellerProfileSchema,
} from "@/schemas";
import {
  createTRPCRouter,
  protectedProcedure,
  publicProcedure,
  sellerProcedure,
} from "@/server/api/trpc";
import { slugify, ensureUniqueSlug } from "@/lib/slug";

export const sellerRouter = createTRPCRouter({
  // Whether the current user already has a seller profile (+ the profile).
  me: protectedProcedure.query(async ({ ctx }) => {
    return ctx.db.sellerProfile.findFirst({
      where: { userId: ctx.user.id, deletedAt: null },
    });
  }),

  // Public storefront by handle, with that seller's published listings.
  byHandle: publicProcedure
    .input(z.object({ handle: handleSchema }))
    .query(async ({ ctx, input }) => {
      const seller = await ctx.db.sellerProfile.findFirst({
        where: { handle: input.handle, deletedAt: null },
        select: {
          handle: true,
          displayName: true,
          bio: true,
          websiteUrl: true,
          listings: {
            where: { status: "PUBLISHED", deletedAt: null },
            select: {
              slug: true,
              name: true,
              tagline: true,
              iconUrl: true,
              ratingAvg: true,
              ratingCount: true,
            },
            orderBy: { ratingAvg: "desc" },
          },
        },
      });
      if (!seller) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Seller not found." });
      }
      return seller;
    }),

  // Complete onboarding: create the seller profile AND their first agent
  // listing (spec + pricing) in one transaction. Either it all lands or none of
  // it does — no half-created seller with an orphaned listing. The seller is
  // marked ACTIVE immediately; the listing starts as DRAFT (the per-listing
  // review gate is the real quality control, handled when they submit it).
  completeOnboarding: protectedProcedure
    .input(onboardingWithListingSchema)
    .mutation(async ({ ctx, input }) => {
      // Block double-onboarding.
      const existing = await ctx.db.sellerProfile.findFirst({
        where: { userId: ctx.user.id },
        select: { id: true },
      });
      if (existing) {
        throw new TRPCError({
          code: "CONFLICT",
          message: "You're already set up as a seller.",
        });
      }

      // Resolve the chosen category slug -> id (if any).
      let categoryId: string | null = null;
      if (input.listing.categorySlug) {
        const cat = await ctx.db.category.findUnique({
          where: { slug: input.listing.categorySlug },
          select: { id: true },
        });
        categoryId = cat?.id ?? null;
      }

      // Unique slug for the listing.
      const slug = await ensureUniqueSlug(ctx.db, slugify(input.listing.name));

      try {
        return await ctx.db.$transaction(async (tx) => {
          const seller = await tx.sellerProfile.create({
            data: {
              userId: ctx.user.id,
              handle: input.profile.handle,
              displayName: input.profile.displayName,
              bio: input.profile.bio,
              websiteUrl: input.profile.websiteUrl,
              status: "ACTIVE",
              payoutStatus: "NOT_STARTED",
              // Record the model of their first listing as their declared intent.
              intendedPricingModel: input.listing.plans[0]?.model,
            },
          });

          const listing = await tx.listing.create({
            data: {
              slug,
              sellerId: seller.id,
              name: input.listing.name,
              tagline: input.listing.tagline,
              description: input.listing.description,
              iconUrl: input.listing.iconUrl,
              status: "DRAFT",
              mcpSpec: {
                create: {
                  transport: input.listing.mcpSpec.transport,
                  endpointUrl: input.listing.mcpSpec.endpointUrl,
                  authType: input.listing.mcpSpec.authType,
                  capabilities: input.listing.mcpSpec.capabilities,
                  protocolVersion: input.listing.mcpSpec.protocolVersion,
                },
              },
              plans: {
                create: input.listing.plans.map((p) => ({
                  name: p.name,
                  model: p.model,
                  priceCents: p.priceCents,
                  currency: p.currency,
                  interval: p.interval,
                  unitPriceCents: p.unitPriceCents,
                  unitLabel: p.unitLabel,
                })),
              },
              ...(categoryId
                ? { categories: { create: [{ categoryId, isPrimary: true }] } }
                : {}),
            },
            include: { mcpSpec: true, plans: true },
          });

          return { seller, listing };
        });
      } catch (e) {
        // Most likely a unique-constraint hit on the handle.
        throw new TRPCError({
          code: "CONFLICT",
          message: "That handle is taken — try another.",
        });
      }
    }),

  // Seller analytics: subscriber counts per listing + summary.
  analytics: sellerProcedure.query(async ({ ctx }) => {
    const listings = await ctx.db.listing.findMany({
      where: { sellerId: ctx.seller.id, deletedAt: null },
      select: { id: true, name: true, slug: true, status: true },
      orderBy: { name: "asc" },
    });

    const listingIds = listings.map((l) => l.id);

    // Count ACTIVE subscriptions per listing from the source of truth.
    const counts = listingIds.length > 0
      ? await ctx.db.subscription.groupBy({
          by: ["listingId"],
          where: { listingId: { in: listingIds }, status: "ACTIVE" },
          _count: { id: true },
        })
      : [];

    const countMap = new Map(counts.map((c) => [c.listingId, c._count.id]));

    const perListing = listings.map((l) => ({
      listingId: l.id,
      name: l.name,
      slug: l.slug,
      status: l.status,
      activeSubscribers: countMap.get(l.id) ?? 0,
    }));

    const totalActiveSubscribers = perListing.reduce((sum, l) => sum + l.activeSubscribers, 0);
    const publishedListings = listings.filter((l) => l.status === "PUBLISHED").length;

    return {
      listings: perListing,
      summary: {
        totalActiveSubscribers,
        totalListings: listings.length,
        publishedListings,
      },
    };
  }),

  // Update storefront details (not the handle — that's URL-stable).
  update: sellerProcedure
    .input(updateSellerProfileSchema)
    .mutation(async ({ ctx, input }) => {
      return ctx.db.sellerProfile.update({
        where: { id: ctx.seller.id },
        data: input,
      });
    }),

  // ---- Stripe Connect onboarding -----------------------------------------
  // Creates a Connect Express account (if needed) and returns an onboarding
  // link URL. The webhook handler updates payoutStatus when Stripe confirms.
  startPayoutOnboarding: sellerProcedure.mutation(async ({ ctx }) => {
    const { stripe } = await import("@/server/stripe/client");
    const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

    let stripeAccountId = ctx.seller.stripeAccountId;

    // Create a Connect Express account if we don't have one yet.
    if (!stripeAccountId) {
      const account = await stripe.accounts.create({
        type: "express",
        email: ctx.user.email,
        metadata: { sellerProfileId: ctx.seller.id },
      });
      stripeAccountId = account.id;

      await ctx.db.sellerProfile.update({
        where: { id: ctx.seller.id },
        data: { stripeAccountId, payoutStatus: "PENDING" },
      });
    }

    const accountLink = await stripe.accountLinks.create({
      account: stripeAccountId,
      refresh_url: `${appUrl}/dashboard`,
      return_url: `${appUrl}/dashboard`,
      type: "account_onboarding",
    });

    return { url: accountLink.url };
  }),

  // Refresh the seller's payout status by querying Stripe directly.
  refreshPayoutStatus: sellerProcedure.mutation(async ({ ctx }) => {
    const { stripe } = await import("@/server/stripe/client");

    if (!ctx.seller.stripeAccountId) {
      throw new TRPCError({
        code: "PRECONDITION_FAILED",
        message: "No Stripe account linked. Start payout onboarding first.",
      });
    }

    const account = await stripe.accounts.retrieve(ctx.seller.stripeAccountId);

    let payoutStatus: "ACTIVE" | "PENDING" | "RESTRICTED";
    if (account.charges_enabled && account.payouts_enabled) {
      payoutStatus = "ACTIVE";
    } else if (account.requirements?.disabled_reason) {
      payoutStatus = "RESTRICTED";
    } else {
      payoutStatus = "PENDING";
    }

    await ctx.db.sellerProfile.update({
      where: { id: ctx.seller.id },
      data: { payoutStatus },
    });

    return { payoutStatus };
  }),
});
