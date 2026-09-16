/**
 * Review router.
 *
 * Rules:
 *  1. Any signed-in user can review. Users with a subscription (current or
 *     historical) are "verified subscribers" — their review is marked verified
 *     and body is optional. Non-subscribers must include written text (min 20
 *     chars) to raise the effort bar against drive-by/fake reviews.
 *  2. The denormalized ratingAvg / ratingCount on Listing stay correct — they're
 *     recomputed inside the same transaction that writes the review, so the
 *     catalog's displayed rating can never drift from reality.
 *
 * The DB-level @@unique([buyerId, listingId]) guarantees one review per buyer
 * per listing; we use upsert so a second submission edits the existing one.
 */
import { TRPCError } from "@trpc/server";
import { createReviewSchema, listingIdSchema } from "@/schemas";
import {
  createTRPCRouter,
  protectedProcedure,
  publicProcedure,
} from "@/server/api/trpc";

export const reviewRouter = createTRPCRouter({
  // Public: list reviews for a listing.
  forListing: publicProcedure
    .input(listingIdSchema)
    .query(async ({ ctx, input }) => {
      return ctx.db.review.findMany({
        where: { listingId: input.id, deletedAt: null },
        orderBy: { createdAt: "desc" },
        include: { buyer: { select: { displayName: true, avatarUrl: true } } },
        take: 100,
      });
    }),

  // Protected: my existing review for a listing (for pre-filling the form).
  myReview: protectedProcedure
    .input(listingIdSchema)
    .query(async ({ ctx, input }) => {
      return ctx.db.review.findFirst({
        where: { buyerId: ctx.user.id, listingId: input.id, deletedAt: null },
        select: { rating: true, body: true, isVerified: true },
      });
    }),

  // Protected: create or update my review for a listing.
  upsert: protectedProcedure
    .input(createReviewSchema)
    .mutation(async ({ ctx, input }) => {
      // Determine verified status: has a subscription (current or historical).
      const hasSub = await ctx.db.subscription.findFirst({
        where: { buyerId: ctx.user.id, listingId: input.listingId },
        select: { id: true },
      });
      const isVerified = !!hasSub;

      // Non-subscribers must include written text (min 20 chars).
      if (!isVerified) {
        const bodyTrimmed = (input.body ?? "").trim();
        if (bodyTrimmed.length < 20) {
          throw new TRPCError({
            code: "BAD_REQUEST",
            message:
              "Written feedback is required (at least 20 characters). Subscribers can leave star-only reviews.",
          });
        }
      }

      // Write review + recompute aggregate atomically.
      return ctx.db.$transaction(async (tx) => {
        await tx.review.upsert({
          where: {
            buyerId_listingId: { buyerId: ctx.user.id, listingId: input.listingId },
          },
          create: {
            buyerId: ctx.user.id,
            listingId: input.listingId,
            rating: input.rating,
            body: input.body,
            isVerified,
          },
          update: {
            rating: input.rating,
            body: input.body,
            isVerified,
            deletedAt: null,
          },
        });

        // Recompute from the source of truth rather than incrementally, so the
        // aggregate is self-healing even if a prior write was interrupted.
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
        return updated;
      });
    }),
});
