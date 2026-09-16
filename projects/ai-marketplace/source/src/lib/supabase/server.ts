/**
 * Supabase server-side client (for Server Components, Route Handlers, and the
 * tRPC context). It reads/writes the auth session via Next's cookie store, so
 * the user's logged-in state is available on the server without a round-trip.
 *
 * There are two Supabase clients in this app:
 *   - this server one (cookie-aware, used to identify the user on the server)
 *   - a browser one (src/lib/supabase/client.ts) used by sign-in/up forms
 * Both talk to the same Supabase project; they differ in how they persist the
 * session (httpOnly cookies server-side vs the browser's own storage).
 */
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

type CookieToSet = { name: string; value: string; options?: CookieOptions };

export async function createSupabaseServerClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: CookieToSet[]) {
          // In a Server Component the cookie store is read-only; the middleware
          // is what actually refreshes the session cookie. Swallowing the
          // error here is the documented pattern.
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            /* called from a Server Component — safe to ignore */
          }
        },
      },
    },
  );
}
