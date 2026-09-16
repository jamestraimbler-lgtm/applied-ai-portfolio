"use client";

/**
 * Seller analytics — subscriber counts per listing and an overall summary.
 * Shown at the top of the seller dashboard.
 */
import { api } from "@/lib/trpc";

const STATUS_STYLES: Record<string, { bg: string; fg: string; label: string }> = {
  DRAFT: { bg: "#eceaf5", fg: "#4a4860", label: "Draft" },
  IN_REVIEW: { bg: "#fdf3e0", fg: "#8a5a12", label: "In review" },
  PUBLISHED: { bg: "#e4f5ee", fg: "#0f7a5a", label: "Published" },
  REJECTED: { bg: "#fbecea", fg: "#c0362c", label: "Needs changes" },
  SUSPENDED: { bg: "#fbecea", fg: "#c0362c", label: "Suspended" },
  ARCHIVED: { bg: "#eee", fg: "#666", label: "Archived" },
};

export function SellerAnalytics() {
  const { data, isLoading } = api.seller.analytics.useQuery();

  if (isLoading || !data) return null;
  if (data.summary.totalListings === 0) return null;

  const { summary, listings } = data;

  return (
    <section style={{ marginBottom: "1.5rem" }}>
      {/* Summary stats — segmented panel */}
      <div
        style={{
          display: "inline-flex",
          gap: "1px",
          background: "var(--line)",
          borderRadius: "var(--radius-lg)",
          overflow: "hidden",
          marginBottom: "1rem",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.15rem", padding: "0.8rem 1.4rem", background: "var(--surface-raised, #FFFDFA)" }}>
          <span style={{ fontWeight: 500, fontSize: "1.4rem", letterSpacing: "-0.02em", color: "var(--accent)", lineHeight: 1.2 }}>
            {summary.totalActiveSubscribers}
          </span>
          <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>subscribers</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.15rem", padding: "0.8rem 1.4rem", background: "var(--surface-raised, #FFFDFA)" }}>
          <span style={{ fontWeight: 500, fontSize: "1.4rem", letterSpacing: "-0.02em", color: "var(--accent)", lineHeight: 1.2 }}>
            {summary.publishedListings}
          </span>
          <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>published</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.15rem", padding: "0.8rem 1.4rem", background: "var(--surface-raised, #FFFDFA)" }}>
          <span style={{ fontWeight: 500, fontSize: "1.4rem", letterSpacing: "-0.02em", color: "var(--accent)", lineHeight: 1.2 }}>
            {summary.totalListings}
          </span>
          <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>total listings</span>
        </div>
      </div>

      {/* Per-listing breakdown */}
      <div
        style={{
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-lg)",
          background: "var(--paper)",
          overflow: "hidden",
        }}
      >
        {listings.map((l, i) => {
          const s = STATUS_STYLES[l.status] ?? STATUS_STYLES.DRAFT!;
          return (
            <div
              key={l.listingId}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "0.75rem",
                padding: "0.65rem 1rem",
                borderTop: i > 0 ? "1px solid var(--line)" : "none",
                fontSize: "0.88rem",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0 }}>
                <span style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {l.name}
                </span>
                <span
                  style={{
                    background: s.bg,
                    color: s.fg,
                    fontSize: "0.68rem",
                    fontWeight: 600,
                    padding: "0.15rem 0.45rem",
                    borderRadius: 999,
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                  }}
                >
                  {s.label}
                </span>
              </div>
              <span
                style={{
                  fontFamily: "ui-monospace, 'SF Mono', 'Menlo', monospace",
                  fontWeight: 600,
                  fontSize: "0.85rem",
                  color: l.activeSubscribers > 0 ? "var(--ink)" : "var(--muted)",
                  flexShrink: 0,
                }}
              >
                {l.activeSubscribers}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
