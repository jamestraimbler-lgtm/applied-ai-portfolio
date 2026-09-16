/**
 * /sell — the "become a seller" landing page. Routes the CTA based on state:
 *  - signed out -> sign in first
 *  - already a seller -> go to dashboard
 *  - signed in, not a seller -> start onboarding
 */
import Link from "next/link";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { db } from "@/server/db/client";

export default async function SellLandingPage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  let isSeller = false;
  if (user) {
    const seller = await db.sellerProfile.findFirst({
      where: { user: { authId: user.id }, deletedAt: null },
      select: { id: true },
    });
    isSeller = !!seller;
  }

  const ctaHref = !user ? "/sign-in" : isSeller ? "/dashboard" : "/sell/onboarding";
  const ctaLabel = !user ? "Sign in to start" : isSeller ? "Go to your dashboard" : "Start listing";

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "0 1.25rem" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1.25rem 0", borderBottom: "1px solid var(--line)" }}>
        <Link href="/" style={{ fontWeight: 600, letterSpacing: "-0.01em", color: "var(--ink)" }}>
          <span style={{ color: "var(--accent)" }}>[</span>ai<span style={{ color: "var(--accent)" }}>]</span> marketplace
        </Link>
        <Link href="/" style={{ fontSize: "0.9rem", color: "var(--muted)" }}>Back to marketplace</Link>
      </header>

      <section style={{ padding: "3rem 0 2rem" }}>
        <h1 style={{ fontSize: "2.1rem", fontWeight: 600, letterSpacing: "-0.025em", margin: "0 0 0.6rem", maxWidth: 520 }}>
          List your AI agent. Reach buyers who can connect it in one click.
        </h1>
        <p style={{ color: "var(--muted)", fontSize: "1.02rem", margin: "0 0 1.75rem", maxWidth: 520 }}>
          Publish your MCP server to the marketplace, set your pricing, and let buyers
          plug it straight into their tools. Every listing is reviewed before it goes live.
        </p>
        <Link className="btn" href={ctaHref} style={{ display: "inline-block", textDecoration: "none", padding: "0.75rem 1.4rem" }}>
          {ctaLabel}
        </Link>
      </section>

      <section style={{ display: "grid", gap: "1rem", paddingBottom: "3rem" }}>
        {[
          ["Set up your storefront", "A public profile buyers can browse and trust."],
          ["Describe your agent", "What it does, how it connects, what it exposes."],
          ["Choose how you charge", "Free, subscription, or usage-based pricing."],
          ["Get reviewed and go live", "An approval check looks it over, then it’s listed."],
        ].map(([title, desc], i) => (
          <div key={i} style={{ display: "flex", gap: "1rem", padding: "1rem 1.1rem", border: "1px solid var(--line)", borderRadius: "var(--radius-lg)", background: "var(--paper)" }}>
            <div style={{ fontWeight: 600, color: "var(--accent)", minWidth: "1.5rem" }}>{i + 1}</div>
            <div>
              <div style={{ fontWeight: 600 }}>{title}</div>
              <div style={{ color: "var(--muted)", fontSize: "0.9rem" }}>{desc}</div>
            </div>
          </div>
        ))}
      </section>
    </main>
  );
}
