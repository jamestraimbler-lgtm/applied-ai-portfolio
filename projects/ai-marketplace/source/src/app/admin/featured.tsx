"use client";

import { api } from "@/lib/trpc";

export function FeaturedManager() {
  const utils = api.useUtils();
  const { data, isLoading } = api.admin.publishedListings.useQuery();

  const toggle = api.admin.setFeatured.useMutation({
    onSuccess: () => utils.admin.publishedListings.invalidate(),
  });

  if (isLoading) return <p style={{ color: "var(--muted)" }}>Loading...</p>;
  if (!data || data.length === 0) {
    return <p style={{ color: "var(--muted)" }}>No published listings to feature.</p>;
  }

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.4rem" }}>
      {data.map((l) => (
        <li
          key={l.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "0.6rem 0.9rem",
            border: `1px solid ${l.isFeatured ? "var(--accent)" : "var(--line)"}`,
            borderRadius: "var(--radius)",
            background: l.isFeatured ? "var(--accent-tint)" : "var(--paper)",
          }}
        >
          <span style={{ fontWeight: l.isFeatured ? 600 : 400 }}>
            {l.name}
            {l.isFeatured && (
              <span style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--accent)", marginLeft: "0.5rem", letterSpacing: "0.04em" }}>
                FEATURED
              </span>
            )}
          </span>
          <button
            className="btn btn-ghost"
            style={{ padding: "0.3rem 0.7rem", fontSize: "0.82rem" }}
            onClick={() => toggle.mutate({ listingId: l.id, featured: !l.isFeatured })}
            disabled={toggle.isPending}
          >
            {l.isFeatured ? "Unfeature" : "Feature"}
          </button>
        </li>
      ))}
    </ul>
  );
}
