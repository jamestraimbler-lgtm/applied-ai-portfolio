/**
 * tRPC HTTP endpoint (App Router).
 *
 * Every tRPC call from the client hits this catch-all route. The fetch adapter
 * turns the request into a procedure call against our appRouter, building a
 * fresh Context (db + authed user) per request.
 *
 * This is the single HTTP surface for the entire API — add a router in root.ts
 * and it's reachable here automatically, no new endpoint needed.
 */
import { fetchRequestHandler } from "@trpc/server/adapters/fetch";
import { type NextRequest } from "next/server";
import { appRouter } from "@/server/api/root";
import { createContext } from "@/server/api/context";

const handler = (req: NextRequest) =>
  fetchRequestHandler({
    endpoint: "/api/trpc",
    req,
    router: appRouter,
    createContext: () => createContext({ headers: req.headers }),
    onError({ path, error }) {
      // Server-side log so failures are visible in dev; swap for your logger.
      if (process.env.NODE_ENV === "development") {
        console.error(`tRPC failed on ${path ?? "<no-path>"}: ${error.message}`);
      }
    },
  });

// App Router requires named exports per HTTP method.
export { handler as GET, handler as POST };
