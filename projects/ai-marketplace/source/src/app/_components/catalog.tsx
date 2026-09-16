"use client";

/**
 * Catalog — the buyer-facing storefront grid. Search + sort, and "spec-strip"
 * cards: each card leads with the agent's name and surfaces its technical
 * signals (transport, tool count, auth) in a mono capability strip, because for
 * this audience "what it exposes / how it connects" is the buying information.
 */
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/trpc";
import { priceLabel, toolCount, transportLabel } from "@/lib/listing-format";
import styles from "./storefront.module.css";

type Sort = "top_rated" | "newest" | "most_popular";
type Price = "all" | "free" | "paid";

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("");
}

export function Catalog() {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("top_rated");
  const [price, setPrice] = useState<Price>("all");
  const [category, setCategory] = useState<string | undefined>(undefined);

  const { data: cats } = api.listing.categories.useQuery();
  const { data, isLoading, error } = api.listing.list.useQuery({
    search: search.trim() || undefined,
    categorySlug: category,
    price,
    sort,
    limit: 30,
  });

  return (
    <>
      <div className={styles.controls}>
        <div className={styles.search}>
          <span className={styles.icon}>⌕</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search agents…"
            aria-label="Search agents"
          />
        </div>
        <div className={styles.filterGroup}>
          {(["all", "free", "paid"] as const).map((v) => (
            <button
              key={v}
              className={`${styles.pill} ${price === v ? styles.pillActive : ""}`}
              onClick={() => setPrice(v)}
              style={{ fontSize: "0.8rem", padding: "0.3rem 0.7rem" }}
            >
              {v === "all" ? "All" : v === "free" ? "Free" : "Paid"}
            </button>
          ))}
        </div>
        <div className={styles.sort}>
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
            <option value="top_rated">Top rated</option>
            <option value="most_popular">Most popular</option>
            <option value="newest">Newest</option>
          </select>
        </div>
      </div>

      {cats && cats.length > 0 && (
        <div className={styles.pills}>
          <button
            className={`${styles.pill} ${!category ? styles.pillActive : ""}`}
            onClick={() => setCategory(undefined)}
          >
            All
          </button>
          {cats.map((c) => (
            <button
              key={c.slug}
              className={`${styles.pill} ${category === c.slug ? styles.pillActive : ""}`}
              onClick={() => setCategory(category === c.slug ? undefined : c.slug)}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      <div className={styles.grid}>
        {isLoading && <div className={styles.empty}>Loading agents…</div>}
        {error && <div className={styles.empty}>Couldn’t load the catalog: {error.message}</div>}
        {data && data.items.length === 0 && (
          <div className={styles.empty}>
            {search ? `No agents match “${search}”.` : "No agents listed yet. Check back soon."}
          </div>
        )}

        {data?.items.map((listing) => {
          const price = priceLabel(listing.plans ?? []);
          const tools = toolCount(listing.mcpSpec?.capabilities);
          return (
            <Link key={listing.id} href={`/agents/${listing.slug}`} className={styles.card}>
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
          );
        })}
      </div>
    </>
  );
}
