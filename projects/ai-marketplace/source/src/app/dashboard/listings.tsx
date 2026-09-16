"use client";

/**
 * Dashboard listings — shows the seller's listings with status badges, the
 * "Submit for review" action, and the approval agent's verdict + reasoning
 * after a review runs (why it was rejected/escalated, or that it's live).
 */
import Link from "next/link";
import { api } from "@/lib/trpc";

const STATUS_STYLES: Record<string, { bg: string; fg: string; label: string }> = {
  DRAFT: { bg: "#eceaf5", fg: "#4a4860", label: "Draft" },
  IN_REVIEW: { bg: "#fdf3e0", fg: "#8a5a12", label: "In review" },
  PUBLISHED: { bg: "#e4f5ee", fg: "#0f7a5a", label: "Published" },
  REJECTED: { bg: "#fbecea", fg: "#c0362c", label: "Needs changes" },
  SUSPENDED: { bg: "#fbecea", fg: "#c0362c", label: "Suspended" },
  ARCHIVED: { bg: "#eee", fg: "#666", label: "Archived" },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.DRAFT!;
  return (
    <span style={{ background: s.bg, color: s.fg, fontSize: "0.75rem", fontWeight: 600, padding: "0.2rem 0.6rem", borderRadius: 999 }}>
      {s.label}
    </span>
  );
}

interface ListingRow {
  id: string;
  name: string;
  tagline: string;
  status: string;
  plans?: unknown[];
  mcpSpec?: { transport: string } | null;
}

function ReviewFeedback({ listingId, status }: { listingId: string; status: string }) {
  // Only fetch a verdict for listings that have been through review.
  const enabled = ["PUBLISHED", "REJECTED", "IN_REVIEW"].includes(status);
  const { data } = api.listing.latestReview.useQuery({ id: listingId }, { enabled });
  if (!data || !data.reasoning) return null;

  const tone =
    data.verdict === "APPROVED"
      ? { bg: "var(--accent-tint)", fg: "var(--accent)", label: "Approved" }
      : data.verdict === "REJECTED"
        ? { bg: "var(--danger-tint)", fg: "var(--danger)", label: "Declined" }
        : { bg: "#fdf3e0", fg: "#8a5a12", label: "Escalated to a human reviewer" };

  return (
    <div style={{ marginTop: "0.75rem", padding: "0.75rem 0.9rem", background: tone.bg, borderRadius: "var(--radius)", fontSize: "0.85rem" }}>
      <div style={{ fontWeight: 600, color: tone.fg, marginBottom: "0.2rem" }}>
        {tone.label}
        {typeof data.riskScore === "number" && (
          <span style={{ fontWeight: 400, color: "var(--muted)" }}> · risk {data.riskScore}/100</span>
        )}
      </div>
      <div style={{ color: "var(--ink-soft)" }}>{data.reasoning}</div>
    </div>
  );
}

export function DashboardListings() {
  const utils = api.useUtils();
  const { data, isLoading, error } = api.listing.mine.useQuery();

  const submit = api.listing.submitForReview.useMutation({
    onSuccess: (_res, vars) => {
      utils.listing.mine.invalidate();
      utils.listing.latestReview.invalidate({ id: vars.id });
    },
  });

  if (isLoading) return <p style={{ color: "var(--muted)" }}>Loading your listings…</p>;
  if (error) return <p style={{ color: "var(--danger)" }}>Couldn’t load: {error.message}</p>;
  if (!data || data.length === 0) {
    return (
      <div style={{ padding: "2rem", border: "1px dashed var(--line-strong)", borderRadius: "var(--radius-lg)", background: "var(--paper)", color: "var(--muted)" }}>
        You don’t have any listings yet.
      </div>
    );
  }

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.75rem" }}>
      {(data as ListingRow[]).map((listing) => {
        const planCount = Array.isArray(listing.plans) ? listing.plans.length : 0;
        const submittable = listing.status === "DRAFT" || listing.status === "REJECTED";
        return (
          <li key={listing.id} style={{ padding: "1.1rem 1.2rem", border: "1px solid var(--line)", borderRadius: "var(--radius-lg)", background: "var(--paper)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                  <span style={{ fontWeight: 600 }}>{listing.name}</span>
                  <StatusBadge status={listing.status} />
                </div>
                <div style={{ color: "var(--ink-soft)", fontSize: "0.9rem", marginTop: "0.2rem" }}>{listing.tagline}</div>
                <div style={{ color: "var(--muted)", fontSize: "0.82rem", marginTop: "0.4rem" }}>
                  {planCount} plan{planCount === 1 ? "" : "s"}
                  {listing.mcpSpec ? ` · ${listing.mcpSpec.transport}` : ""}
                </div>
              </div>

              <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
                <Link
                  className="btn btn-ghost"
                  href={`/dashboard/listings/${listing.id}/edit`}
                  style={{ padding: "0.5rem 0.9rem", whiteSpace: "nowrap" }}
                >
                  Edit
                </Link>
                {submittable && (
                  <button
                    className={listing.status === "REJECTED" ? "btn btn-ghost" : "btn"}
                    style={{ padding: "0.5rem 0.9rem", whiteSpace: "nowrap" }}
                    onClick={() => submit.mutate({ id: listing.id })}
                    disabled={submit.isPending}
                  >
                    {submit.isPending ? "Reviewing…" : listing.status === "REJECTED" ? "Resubmit" : "Submit for review"}
                  </button>
                )}
              </div>
            </div>

            <ReviewFeedback listingId={listing.id} status={listing.status} />
          </li>
        );
      })}
    </ul>
  );
}
