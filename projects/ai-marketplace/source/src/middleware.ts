/**
 * Next middleware — keeps the Supabase auth session fresh.
 *
 * Supabase access tokens expire; this runs on every request, reads the session
 * cookie, and writes back a refreshed one when needed. Without it, sessions
 * silently expire and Server Components see the user as logged out. This is the
 * documented Supabase SSR pattern.
 */
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

type CookieToSet = { name: string; value: string; options?: CookieOptions };

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: CookieToSet[]) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  // Touching getUser() triggers the refresh-and-set-cookie cycle above.
  await supabase.auth.getUser();

  return response;
}

export const config = {
  // Run on everything except static assets, image optimization, webhooks, and
  // the gateway (gateway auth is via access key, not a logged-in session).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/webhooks|api/gateway|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
