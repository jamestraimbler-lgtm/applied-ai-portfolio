/**
 * /admin — the escalation queue, admins only.
 *
 * Guard: signed in AND isAdmin on the User row. Anyone else is redirected home.
 */
import { redirect } from "next/navigation";
import Link from "next/link";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { db } from "@/server/db/client";
import { signOut } from "../(auth)/actions";
import { EscalationQueue } from "./queue";
import { FeaturedManager } from "./featured";

export default async function AdminPage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/sign-in");

  const me = await db.user.findFirst({
    where: { authId: user.id },
    select: { isAdmin: true },
  });
  if (!me?.isAdmin) redirect("/");

  return (
    <main style={{ maxWidth: 880, margin: "0 auto", padding: "0 1.25rem" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1.25rem 0", borderBottom: "1px solid var(--line)" }}>
        <Link href="/" style={{ fontWeight: 600, letterSpacing: "-0.01em", color: "var(--ink)" }}>
          <span style={{ color: "var(--accent)" }}>[</span>ai<span style={{ color: "var(--accent)" }}>]</span> marketplace
        </Link>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", fontSize: "0.9rem" }}>
          <span style={{ background: "var(--accent-tint)", color: "var(--accent)", fontSize: "0.72rem", fontWeight: 700, padding: "0.2rem 0.55rem", borderRadius: 999, letterSpacing: "0.04em" }}>ADMIN</span>
          <Link href="/">Marketplace</Link>
          <form action={signOut}>
            <button className="btn btn-ghost" type="submit" style={{ padding: "0.4rem 0.8rem" }}>Sign out</button>
          </form>
        </div>
      </header>

      <section style={{ padding: "2.5rem 0 1.5rem" }}>
        <h1 style={{ fontSize: "1.7rem", fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 0.3rem" }}>
          Review queue
        </h1>
        <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.92rem", maxWidth: 560 }}>
          Listings the approval agent escalated for a human decision. Approving
          publishes the listing; declining sends it back to the seller.
        </p>
      </section>

      <EscalationQueue />

      <section style={{ padding: "2.5rem 0 1.5rem" }}>
        <h2 style={{ fontSize: "1.3rem", fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 0.3rem" }}>
          Featured listing
        </h2>
        <p style={{ color: "var(--muted)", margin: "0 0 1rem", fontSize: "0.92rem" }}>
          Pick one published listing to feature on the homepage.
        </p>
        <FeaturedManager />
      </section>
    </main>
  );
}
