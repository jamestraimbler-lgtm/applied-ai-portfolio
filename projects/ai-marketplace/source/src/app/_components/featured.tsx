"use client";

import Link from "next/link";
import { api } from "@/lib/trpc";
import { priceLabel, toolCount, transportLabel } from "@/lib/listing-format";
import styles from "./storefront.module.css";

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("");
}

export function FeaturedAgent() {
  const { data: listing } = api.listing.featured.useQuery();

  if (!listing) return null;

  const price = priceLabel(listing.plans ?? []);
  const tools = toolCount(listing.mcpSpec?.capabilities);

  return (
    <section className={styles.featuredSection}>
      <div className={styles.featuredLabel}>Editor&#39;s pick</div>
      <Link href={`/agents/${listing.slug}`} className={styles.featuredCard}>
        <div className={styles.cardHead}>
          <div className={styles.cardIcon}>{initials(listing.name)}</div>
          <div>
            <div className={styles.cardName}>{listing.name}</div>
            <div className={styles.cardSeller}>{listing.seller?.displayName ?? "Unknown"}</div>
          </div>
        </div>
        <div className={styles.cardTagline}>{listing.tagline}</div>
        <div className={styles.spec}>
          <span className={styles.chip}>{transportLabel(listing.mcpSpec?.transport)}</span>
          <span className={styles.chip}>
            <b>{tools}</b> tool{tools === 1 ? "" : "s"}
          </span>
          <span className={styles.chip}>
            {listing.mcpSpec?.authType === "NONE" ? "no auth" : (listing.mcpSpec?.authType ?? "—").toLowerCase()}
          </span>
        </div>
        <div className={styles.cardFoot}>
          <span className={styles.price}>
            {price.main}
            {price.sub && <span className={styles.priceSub}> {price.sub}</span>}
          </span>
          <span className={styles.rating}>
            {listing.ratingCount > 0 ? `★ ${listing.ratingAvg.toFixed(1)} (${listing.ratingCount})` : "No reviews yet"}
          </span>
        </div>
      </Link>
    </section>
  );
}
