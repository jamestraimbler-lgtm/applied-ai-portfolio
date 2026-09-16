/**
 * tRPC request context.
 *
 * Created once per request. It carries:
 *  - `db`: the Prisma client
 *  - `user`: the authenticated app User (or null), resolved from the Supabase
 *    auth session.
 *
 * Flow: Supabase stores the session in cookies -> we read it server-side ->
 * map the Supabase user (its `id` and `email`) to our own `User` row. All
 * downstream code works with our domain model, never Supabase's user object.
 * We upsert on first sight so a freshly-signed-up user gets a domain record
 * automatically, and we keep their email in sync on every request.
 */
import type { User } from "@prisma/client";
import { db } from "@/server/db/client";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export interface Context {
  db: typeof db;
  /** The authenticated app user, or null if the request is anonymous. */
  user: User | null;
}

/**
 * Build the context for an incoming request. Called by the tRPC adapter.
 */
export async function createContext(_opts: { headers: Headers }): Promise<Context> {
  const supabase = await createSupabaseServerClient();

  // getUser() validates the session against Supabase (more trustworthy than
  // getSession(), which only decodes the local cookie).
  const {
    data: { user: supabaseUser },
  } = await supabase.auth.getUser();

  let user: User | null = null;
  if (supabaseUser) {
    // Map Supabase identity -> our User. Supabase's user id is our `authId`.
    user = await db.user.upsert({
      where: { authId: supabaseUser.id },
      update: { email: supabaseUser.email ?? undefined },
      create: {
        authId: supabaseUser.id,
        email: supabaseUser.email ?? `${supabaseUser.id}@placeholder.local`,
      },
    });
  }

  return { db, user };
}
