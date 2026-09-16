/**
 * tRPC initialization + procedure types.
 *
 * This file defines the *kinds* of procedures available, layered by access:
 *
 *   publicProcedure    — anyone, even anonymous
 *   protectedProcedure — any signed-in user (ctx.user guaranteed non-null)
 *   sellerProcedure    — signed-in user who has a SellerProfile (ctx.seller set)
 *   adminProcedure     — signed-in user with isAdmin
 *
 * Each layer is a middleware that narrows the context type, so inside a
 * sellerProcedure resolver TypeScript *knows* ctx.seller exists. That's the
 * type safety paying off: the selected middleware exposes a narrowed context.
 * Callers must still select the correct procedure and scope database queries.
 */
import { initTRPC, TRPCError } from "@trpc/server";
import superjson from "superjson";
import { ZodError } from "zod";
import type { Context } from "./context";

const t = initTRPC.context<Context>().create({
  // superjson lets Dates, BigInts, etc. cross the wire without manual
  // serialization — important since money-adjacent and timestamp fields are
  // everywhere.
  transformer: superjson,
  errorFormatter({ shape, error }) {
    return {
      ...shape,
      data: {
        ...shape.data,
        // Surface Zod field errors to the client in a structured way so forms
        // can show per-field messages.
        zod: error.cause instanceof ZodError ? error.cause.flatten() : null,
      },
    };
  },
});

export const createTRPCRouter = t.router;
export const createCallerFactory = t.createCallerFactory;
export const mergeRouters = t.mergeRouters;

/** Open to everyone. */
export const publicProcedure = t.procedure;

/** Requires a signed-in user. Narrows ctx.user to non-null. */
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
