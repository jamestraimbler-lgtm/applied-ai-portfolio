/**
 * Supabase browser client — used by client components (sign-in / sign-up
 * forms, sign-out button). It persists the session in the browser and keeps
 * the auth cookies in sync so the server client can read them.
 */
"use client";

import { createBrowserClient } from "@supabase/ssr";

export function createSupabaseBrowserClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
