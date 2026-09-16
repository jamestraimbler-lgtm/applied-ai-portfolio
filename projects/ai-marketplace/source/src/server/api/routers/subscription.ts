/**
 * Subscription router.
 *
 * This manages the buyer <-> listing relationship and its billing state. The
 * actual money movement lives in Stripe — this router owns the *domain* state
 * (who has access to what, under which plan) and mirrors Stripe's billing
 * state for fast access checks.
 *
 * IMPORTANT — the payment boundary:
 * Creating a charge / Stripe Checkout session is deliberately left as a clearly
 * marked integration point, not faked here. The flow is:
 *   1. `create` makes an INCOMPLETE Subscription row and (TODO) a Stripe
 *      Checkout session, returning its URL.
 *   2. The buyer completes payment on Stripe.
 *   3. A Stripe webhook flips the row to ACTIVE and fills in the billing fields.
 * That way access is only ever granted against confirmed payment from Stripe,
 * never optimistically in the app.
 */
import { z } from "zod";
import { TRPCError } from "@trpc/server";
import {
  createSubscriptionSchema,
  subscriptionIdSchema,
} from "@/schemas";
import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import {
  generateAccessKey,
  encryptAccessKey,
  decryptAccessKey,
  hashAccessKey,
} from "@/server/crypto/access-key";

export const subscriptionRouter = createTRPCRouter({
  // My subscriptions (the "my purchased agents" view).
  mine: protectedProcedure.query(async ({ ctx }) => {
    return ctx.db.subscription.findMany({
      where: {
        buyerId: ctx.user.id,
        status: { in: ["ACTIVE", "PAST_DUE", "PAUSED"] },
      },
      orderBy: { createdAt: "desc" },
      include: {
        listing: {
          select: { slug: true, name: true, iconUrl: true, status: true },
        },
        plan: { select: { name: true, model: true, priceCents: true, currency: true } },
      },
    });
  }),

  // Whether I have an active subscription to a given listing (for gating UI).
  statusForListing: protectedProcedure
    .input(createSubscriptionSchema.pick({ listingId: true }))
    .query(async ({ ctx, input }) => {
      const sub = await ctx.db.subscription.findFirst({
        where: { buyerId: ctx.user.id, listingId: input.listingId, status: "ACTIVE" },
        select: { id: true, currentPeriodEnd: true, cancelAtPeriodEnd: true },
      });
      return { active: !!sub, subscription: sub };
    }),

  // Begin a subscription. Creates the domain row in INCOMPLETE state; the
  // Stripe Checkout session is the integration point below.
  create: protectedProcedure
    .input(createSubscriptionSchema)
    .mutation(async ({ ctx, input }) => {
      // Validate the plan belongs to the listing and both are live.
      const plan = await ctx.db.pricingPlan.findFirst({
        where: { id: input.planId, listingId: input.listingId, isActive: true },
        include: { listing: { select: { status: true, deletedAt: true, sellerId: true, slug: true } } },
      });
      // `listing` is an included relation; guard it explicitly.
      const listing = plan?.listing;
      if (!plan || !listing || listing.status !== "PUBLISHED" || listing.deletedAt) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: "That plan isn't available.",
        });
      }

      // Enforce the one-active-subscription-per-listing rule (app-level).
      const existingActive = await ctx.db.subscription.findFirst({
        where: {
          buyerId: ctx.user.id,
          listingId: input.listingId,
          status: { in: ["ACTIVE", "PAST_DUE", "INCOMPLETE"] },
        },
        select: { id: true },
      });
      if (existingActive) {
        throw new TRPCError({
          code: "CONFLICT",
          message: "You already have a subscription to this listing.",
        });
      }

      // Free plans need no payment — grant access immediately.
      if (plan.model === "FREE") {
        // Generate an encrypted access key + hash if the agent uses API_KEY auth.
        let accessKeyCipher: string | undefined;
        let accessKeyHash: string | undefined;
        const spec = await ctx.db.mcpSpec.findFirst({
          where: { listingId: input.listingId },
          select: { authType: true },
        });
        if (spec?.authType === "API_KEY") {
          const plainKey = generateAccessKey();
          accessKeyCipher = encryptAccessKey(plainKey);
          accessKeyHash = hashAccessKey(plainKey);
        }

        const sub = await ctx.db.subscription.create({
          data: {
            buyerId: ctx.user.id,
            listingId: input.listingId,
            planId: input.planId,
            status: "ACTIVE",
            accessKeyCipher,
            accessKeyHash,
          },
        });

        // Bump active sub count.
        await ctx.db.listing.update({
          where: { id: input.listingId },
          data: { activeSubCount: { increment: 1 } },
        });

        return sub;
      }

      // Paid plans require the seller to be set up for payouts.
      const seller = await ctx.db.sellerProfile.findFirst({
        where: { id: plan.listing.sellerId, deletedAt: null },
        select: { stripeAccountId: true, payoutStatus: true },
      });
      if (!seller?.stripeAccountId || seller.payoutStatus !== "ACTIVE") {
        throw new TRPCError({
          code: "PRECONDITION_FAILED",
          message: "This seller isn't set up to accept payments yet.",
        });
      }

      // Ensure the plan has a Stripe Price (lazy creation).
      const { ensureStripePriceForPlan } = await import("@/server/stripe/ensure-price");
      const fullPlan = await ctx.db.pricingPlan.findUniqueOrThrow({ where: { id: plan.id } });
      const stripePriceId = await ensureStripePriceForPlan(fullPlan);

      // Create the domain row INCOMPLETE, then hand off to Stripe.
      const sub = await ctx.db.subscription.create({
        data: {
          buyerId: ctx.user.id,
          listingId: input.listingId,
          planId: input.planId,
          status: "INCOMPLETE",
        },
      });

      const { stripe, PLATFORM_FEE_PERCENT } = await import("@/server/stripe/client");
      const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

      const session = await stripe.checkout.sessions.create({
        mode: "subscription",
        line_items: [{ price: stripePriceId, quantity: 1 }],
        metadata: { subscriptionId: sub.id },
        subscription_data: {
          application_fee_percent: PLATFORM_FEE_PERCENT,
          transfer_data: { destination: seller.stripeAccountId },
          metadata: { subscriptionId: sub.id },
        },
        success_url: `${appUrl}/subscriptions?success=1`,
        cancel_url: `${appUrl}/agents/${plan.listing.slug ?? ""}`,
      });

      return { subscriptionId: sub.id, checkoutUrl: session.url };
    }),

  // Cancel at period end (keeps access until the paid period runs out).
  cancel: protectedProcedure
    .input(subscriptionIdSchema)
    .mutation(async ({ ctx, input }) => {
      const sub = await ctx.db.subscription.findFirst({
        where: { id: input.id, buyerId: ctx.user.id },
        select: { id: true, stripeSubscriptionId: true },
      });
      if (!sub) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Subscription not found." });
      }

      // TODO(stripe): call stripe.subscriptions.update(sub.stripeSubscriptionId,
      // { cancel_at_period_end: true }); the webhook reconciles our row. For now
      // we set the intent flag locally.
      await ctx.db.subscription.update({
        where: { id: sub.id },
        data: { cancelAtPeriodEnd: true, canceledAt: new Date() },
      });
      return { ok: true };
    }),

  // Connection details — only for active subscribers. The access gate.
  connectionDetails: protectedProcedure
    .input(z.object({ listingId: z.string().cuid() }))
    .query(async ({ ctx, input }) => {
      const sub = await ctx.db.subscription.findFirst({
        where: {
          buyerId: ctx.user.id,
          listingId: input.listingId,
          status: "ACTIVE",
        },
        select: { id: true, accessKeyCipher: true },
      });
      if (!sub) {
        throw new TRPCError({
          code: "FORBIDDEN",
          message: "You need an active subscription to see connection details.",
        });
      }

      const listing = await ctx.db.listing.findUniqueOrThrow({
        where: { id: input.listingId },
        select: {
          slug: true,
          name: true,
          mcpSpec: {
            select: {
              transport: true,
              endpointUrl: true,
              authType: true,
              protocolVersion: true,
              capabilities: true,
            },
          },
        },
      });

      // Decrypt the access key just-in-time for display.
      let accessKey: string | null = null;
      if (listing.mcpSpec?.authType === "API_KEY" && sub.accessKeyCipher) {
        accessKey = decryptAccessKey(sub.accessKeyCipher);
      }

      return {
        slug: listing.slug,
        name: listing.name,
        transport: listing.mcpSpec?.transport ?? null,
        endpointUrl: listing.mcpSpec?.endpointUrl ?? null,
        authType: listing.mcpSpec?.authType ?? null,
        protocolVersion: listing.mcpSpec?.protocolVersion ?? null,
        capabilities: listing.mcpSpec?.capabilities ?? null,
        accessKey,
      };
    }),
});
