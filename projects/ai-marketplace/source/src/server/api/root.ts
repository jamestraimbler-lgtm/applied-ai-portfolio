/**
 * Root tRPC router. Every sub-router hangs off this, and `AppRouter` is the
 * single type the client imports to get full end-to-end type inference. Add a
 * new feature router here and the client knows about it immediately — no codegen
 * step, no manual API client.
 */
import { createTRPCRouter, createCallerFactory } from "@/server/api/trpc";
import { listingRouter } from "@/server/api/routers/listing";
import { sellerRouter } from "@/server/api/routers/seller";
import { subscriptionRouter } from "@/server/api/routers/subscription";
import { reviewRouter } from "@/server/api/routers/review";
import { adminRouter } from "@/server/api/routers/admin";

export const appRouter = createTRPCRouter({
  listing: listingRouter,
  seller: sellerRouter,
  subscription: subscriptionRouter,
  review: reviewRouter,
  admin: adminRouter,
});

/** The type clients import for inference. This is the API contract. */
export type AppRouter = typeof appRouter;

/** For calling procedures server-side (RSC, tests, scripts) without HTTP. */
export const createCaller = createCallerFactory(appRouter);
