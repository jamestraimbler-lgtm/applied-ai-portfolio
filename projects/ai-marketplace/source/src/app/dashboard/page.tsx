/**
 * /dashboard — the seller's home. Shows their listings and each one's status,
 * with the action to submit a draft for review.
 *
 * Guard: must be signed in AND be a seller; otherwise route them appropriately.
 */
import { redirect } from "next/navigation";
import Link from "next/link";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { db } from "@/server/db/client";
import { signOut } from "../(auth)/actions";
import { SellerAnalytics } from "./analytics";
import { DashboardListings } from "./listings";
import { PayoutsSection } from "./payouts";

export default async function DashboardPage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/sign-in");

  const seller = await db.sellerProfile.findFirst({
    where: { user: { authId: user.id }, deletedAt: null },
    select: { displayName: true, handle: true },
  });
  if (!seller) redirect("/sell");

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: "0 1.25rem" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1.25rem 0", borderBottom: "1px solid var(--line)" }}>
        <Link href="/" style={{ fontWeight: 600, letterSpacing: "-0.01em", color: "var(--ink)" }}>
          <span style={{ color: "var(--accent)" }}>[</span>ai<span style={{ color: "var(--accent)" }}>]</span> marketplace
        </Link>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", fontSize: "0.9rem" }}>
          <Link href="/">Marketplace</Link>
          <form action={signOut}>
            <button className="btn btn-ghost" type="submit" style={{ padding: "0.4rem 0.8rem" }}>Sign out</button>
          </form>
        </div>
      </header>

      <section style={{ padding: "2.5rem 0 1.5rem", display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "1rem" }}>
        <div>
          <h1 style={{ fontSize: "1.7rem", fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 0.3rem" }}>
            {seller.displayName}
          </h1>
          <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.9rem" }}>
            Your seller dashboard · marketplace/sellers/{seller.handle}
          </p>
        </div>
        <Link className="btn" href="/dashboard/listings/new">New listing</Link>
      </section>

      <SellerAnalytics />
      <PayoutsSection />
      <DashboardListings />
    </main>
  );
}
