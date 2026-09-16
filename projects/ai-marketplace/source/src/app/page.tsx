/**
 * Home / storefront. Auth-aware nav + hero stats, featured agent, then the catalog.
 */
import Link from "next/link";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { db } from "@/server/db/client";
import { signOut } from "./(auth)/actions";
import { Catalog } from "./_components/catalog";
import { FeaturedAgent } from "./_components/featured";
import styles from "./_components/storefront.module.css";

export default async function HomePage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  let isSeller = false;
  let isAdmin = false;
  if (user) {
    const me = await db.user.findFirst({
      where: { authId: user.id },
      select: { isAdmin: true, sellerProfile: { select: { id: true, deletedAt: true } } },
    });
    isAdmin = me?.isAdmin ?? false;
    isSeller = !!me?.sellerProfile && !me.sellerProfile.deletedAt;
  }

  // Hero stats — queried server-side so the hero renders instantly.
  const [agentCount, categoryRows] = await Promise.all([
    db.listing.count({ where: { status: "PUBLISHED", deletedAt: null } }),
    db.categoriesOnListings.findMany({
      where: { listing: { status: "PUBLISHED", deletedAt: null } },
      select: { categoryId: true },
      distinct: ["categoryId"],
    }),
  ]);
  const categoryCount = categoryRows.length;

  return (
    <main className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/" className={styles.brand}>
          <span className={styles.bk}>[</span>ai<span className={styles.bk}>]</span> marketplace
        </Link>
        <div className={styles.navRight}>
          {user ? (
            <>
              {isAdmin && <Link href="/admin">Admin</Link>}
              <Link href="/subscriptions">Subscriptions</Link>
              <Link href={isSeller ? "/dashboard" : "/sell"}>{isSeller ? "Dashboard" : "Sell"}</Link>
              <span style={{ color: "var(--muted)" }}>{user.email}</span>
              <form action={signOut}>
                <button className="btn btn-ghost" type="submit" style={{ padding: "0.4rem 0.8rem" }}>Sign out</button>
              </form>
            </>
          ) : (
            <>
              <Link href="/sign-in">Sign in</Link>
              <Link className="btn" href="/sign-up" style={{ padding: "0.4rem 0.9rem", textDecoration: "none" }}>Get started</Link>
            </>
          )}
        </div>
      </nav>

      <section className={styles.hero}>
        <h1>AI agents, ready to connect</h1>
        <p>
          Browse MCP servers and agents you can plug straight into your tools — every
          listing reviewed before it&#39;s here.
          {user && !isSeller && <> Have one to sell? <Link href="/sell">List it.</Link></>}
        </p>
        {agentCount > 0 && (
          <div className={styles.heroStats}>
            <div className={styles.stat}>
              <span className={styles.statNum}>{agentCount}</span>
              <span className={styles.statLabel}>agents</span>
            </div>
            <div className={styles.stat}>
              <span className={styles.statNum}>100%</span>
              <span className={styles.statLabel}>reviewed</span>
            </div>
            {categoryCount > 0 && (
              <div className={styles.stat}>
                <span className={styles.statNum}>{categoryCount}</span>
                <span className={styles.statLabel}>categories</span>
              </div>
            )}
          </div>
        )}
      </section>

      <FeaturedAgent />
      <Catalog />
    </main>
  );
}
