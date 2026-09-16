/**
 * Client-side tRPC + React Query.
 *
 * `api` is the typed client the whole frontend uses, e.g.
 *   const { data } = api.listing.list.useQuery({ sort: "top_rated" });
 * Because it's built from the AppRouter *type*, every input and output is
 * inferred — rename a field on the server and the client stops compiling. No
 * generated SDK, no manual fetch calls, no drift.
 */
"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { httpBatchLink, loggerLink } from "@trpc/client";
import { createTRPCReact } from "@trpc/react-query";
import superjson from "superjson";
import { type AppRouter } from "@/server/api/root";

export const api = createTRPCReact<AppRouter>();

/** Build the base URL for the tRPC endpoint in any environment. */
function getBaseUrl() {
  if (typeof window !== "undefined") return ""; // browser: relative path
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  return `http://localhost:${process.env.PORT ?? 3000}`;
}

/**
 * Wrap the app in this so `api.*` hooks work. One QueryClient per mount
 * (useState) so it isn't shared across requests on the server.
 */
export function TRPCProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Sensible catalog defaults: don't refetch on every focus, keep
            // data fresh-enough for 30s.
            staleTime: 30 * 1000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  const [trpcClient] = useState(() =>
    api.createClient({
      links: [
        loggerLink({
          enabled: (op) =>
            process.env.NODE_ENV === "development" ||
            (op.direction === "down" && op.result instanceof Error),
        }),
        httpBatchLink({
          url: `${getBaseUrl()}/api/trpc`,
          // superjson matches the server transformer so Dates/etc. survive.
          transformer: superjson,
        }),
      ],
    }),
  );

  return (
    <api.Provider client={trpcClient} queryClient={queryClient}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </api.Provider>
  );
}
