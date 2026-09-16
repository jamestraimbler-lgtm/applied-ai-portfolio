/**
 * Admin router — the escalation queue.
 *
 * When the approval agent ESCALATES a listing, it stays IN_REVIEW with a
 * ListingReview row marked ESCALATED, waiting for a human. These procedures let
 * an admin see that queue, inspect a listing with the agent's reasoning, and
 * make the final call.
 *
 * Same invariant as the agent path: the ONLY way a listing becomes PUBLISHED is
 * an approval decision here (human) or in submitForReview (agent). A human
 * resolution writes a new ListingReview row with reviewedBy = HUMAN, preserving
 * the full audit trail (the agent's escalation + the human's verdict).
 */
import { z } from "zod";
import { TRPCError } from "@trpc/server";
import { createTRPCRouter, adminProcedure } from "@/server/api/trpc";

export const adminRouter = createTRPCRouter({
  // The queue: listings currently escalated and waiting on a human. We surface
  // listings that are IN_REVIEW whose most recent review verdict is ESCALATED.
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

  // Full detail for reviewing one escalated listing: everything the agent saw,
  // plus its reasoning and risk flags, so the human can decide with context.
  reviewDetail: adminProcedure
    .input(z.object({ id: z.string().cuid() }))
    .query(async ({ ctx, input }) => {
      const listing = await ctx.db.listing.findFirst({
        where: { id: input.id, deletedAt: null },
        include: {
          seller: { select: { handle: true, displayName: true, bio: true } },
          mcpSpec: true,
          plans: { where: { isActive: true } },
          listingReviews: { orderBy: { createdAt: "desc" }, take: 5 },
        },
      });
      if (!listing) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Listing not found." });
      }
      return listing;
    }),

  // Human resolution of an escalation. Records a HUMAN review row and routes the
  // listing. Only valid while the listing is IN_REVIEW (i.e. actually pending).
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

  // Toggle the featured flag on a published listing. Clears previous featured
  // listing when setting a new one so at most one listing is featured at a time.
  setFeatured: adminProcedure
    .input(z.object({ listingId: z.string().cuid(), featured: z.boolean() }))
    .mutation(async ({ ctx, input }) => {
      if (input.featured) {
        // Clear any existing featured listing first.
        await ctx.db.listing.updateMany({
          where: { isFeatured: true },
          data: { isFeatured: false },
        });
      }
      await ctx.db.listing.update({
        where: { id: input.listingId },
        data: { isFeatured: input.featured },
      });
      return { ok: true };
    }),

  // Published listings for the featured manager.
  publishedListings: adminProcedure.query(async ({ ctx }) => {
    return ctx.db.listing.findMany({
      where: { status: "PUBLISHED", deletedAt: null },
      select: { id: true, name: true, isFeatured: true },
      orderBy: { name: "asc" },
    });
  }),
});
