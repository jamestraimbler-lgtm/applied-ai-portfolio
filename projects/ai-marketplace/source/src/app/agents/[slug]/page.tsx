/**
 * /agents/[slug] — the listing detail page. The buyer's decision surface:
 * what the agent does, the real tools it exposes (the spec), pricing, and the
 * subscribe action. Server Component for the listing data; the subscribe button
 * is a small client island.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { createCaller } from "@/server/api/root";
import { createContext } from "@/server/api/context";
import { TRPCError } from "@trpc/server";
import { priceLabel, extractTools, transportLabel, toolCount } from "@/lib/listing-format";
import { SubscribePanel } from "./subscribe";
import { ReviewsSection } from "./reviews";
import styles from "@/app/_components/storefront.module.css";

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("");
}

export default async function AgentDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;

  // Call the tRPC procedure server-side (no HTTP) for the initial render.
  const ctx = await createContext({ headers: new Headers() });
  const caller = createCaller(ctx);

  let listing;
  try {
    listing = await caller.listing.bySlug({ slug });
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") notFound();
    throw e;
  }

  const tools = extractTools(listing.mcpSpec?.capabilities);
  const price = priceLabel(listing.plans ?? []);

  return (
    <main className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/" className={styles.brand}>
          <span className={styles.bk}>[</span>ai<span className={styles.bk}>]</span> marketplace
        </Link>
        <div className={styles.navRight}>
          <Link href="/">Browse all</Link>
        </div>
      </nav>

      <Link href="/" className={styles.back}>← Back to marketplace</Link>

      <div className={styles.detail}>
        {/* Main column */}
        <div>
          <div className={styles.detailHead}>
            <div className={styles.detailIcon}>{initials(listing.name)}</div>
            <div>
              <h1>{listing.name}</h1>
              <div className={styles.by}>
                by <Link href={`/sellers/${listing.seller?.handle ?? ""}`}>{listing.seller?.displayName ?? "Unknown"}</Link>
                {listing.ratingCount > 0 && <> · ★ {listing.ratingAvg.toFixed(1)} ({listing.ratingCount})</>}
              </div>
            </div>
          </div>

          <p className={styles.detailTagline}>{listing.tagline}</p>

          <div className={styles.sectionLabel}>About</div>
          <div className={styles.prose}>{listing.description}</div>

          <div className={styles.sectionLabel}>Tools it exposes</div>
          {tools.length > 0 ? (
            <div className={styles.tools}>
              {tools.map((t, i) => (
                <div key={i} className={styles.tool}>
                  <span className={styles.toolName}>{t.name}</span>
                  {t.description && <span className={styles.toolDesc}>{t.description}</span>}
                </div>
              ))}
            </div>
          ) : (
            <p className={styles.prose} style={{ color: "var(--muted)" }}>
              This listing hasn’t published a tool list.
            </p>
          )}

          <ReviewsSection listingId={listing.id} />
        </div>

        {/* Purchase rail */}
        <aside className={styles.rail}>
          <div className={styles.railPrice}>
            {price.main}
            {price.sub && <span className={styles.per}> {price.sub}</span>}
          </div>
          <div className={styles.railPlan}>
            {listing.plans?.length ?? 0} plan{(listing.plans?.length ?? 0) === 1 ? "" : "s"} available
          </div>

          <div className={styles.railSpec}>
            <div className={styles.railRow}>
              <span className="k">Transport</span>
              <span className="v">{transportLabel(listing.mcpSpec?.transport)}</span>
            </div>
            <div className={styles.railRow}>
              <span className="k">Tools</span>
              <span className="v">{toolCount(listing.mcpSpec?.capabilities)}</span>
            </div>
            <div className={styles.railRow}>
              <span className="k">Auth</span>
              <span className="v">{(listing.mcpSpec?.authType ?? "—").toLowerCase()}</span>
            </div>
          </div>

          <SubscribePanel
            listingId={listing.id}
            plans={(listing.plans ?? []).map((p) => ({
              id: p.id,
              name: p.name,
              model: p.model,
              priceCents: p.priceCents,
              currency: p.currency,
              interval: p.interval,
              unitPriceCents: p.unitPriceCents,
              unitLabel: p.unitLabel,
            }))}
          />
        </aside>
      </div>
    </main>
  );
}
