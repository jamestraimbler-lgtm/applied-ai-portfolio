"use client";

/**
 * Subscription list — the buyer's active subscriptions with a cancel action.
 * Cancel sets cancel-at-period-end (keeps access until the period runs out);
 * for free plans that's effectively immediate at the domain level.
 */
import Link from "next/link";
import { api } from "@/lib/trpc";
import { priceLabel } from "@/lib/listing-format";

export function SubscriptionList() {
  const utils = api.useUtils();
  const { data, isLoading, error } = api.subscription.mine.useQuery();

  const cancel = api.subscription.cancel.useMutation({
    onSuccess: () => utils.subscription.mine.invalidate(),
  });

  if (isLoading) return <p style={{ color: "var(--muted)" }}>Loading…</p>;
  if (error) return <p style={{ color: "var(--danger)" }}>Couldn’t load: {error.message}</p>;

  if (!data || data.length === 0) {
    return (
      <div style={{ padding: "2.5rem 2rem", textAlign: "center", border: "1px dashed var(--line-strong)", borderRadius: "var(--radius-lg)", background: "var(--paper)", color: "var(--muted)" }}>
        You haven’t subscribed to anything yet.{" "}
        <Link href="/">Browse the marketplace.</Link>
      </div>
    );
  }

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: "0 0 4rem", display: "grid", gap: "0.75rem" }}>
      {data.map((sub) => {
        const pl = sub.plan ? priceLabel([sub.plan]) : { main: "—" };
        return (
          <li key={sub.id} style={{ padding: "1.1rem 1.2rem", border: "1px solid var(--line)", borderRadius: "var(--radius-lg)", background: "var(--paper)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
              <div>
                <Link href={`/agents/${sub.listing?.slug ?? ""}`} style={{ fontWeight: 600, color: "var(--ink)" }}>
                  {sub.listing?.name ?? "Unknown agent"}
                </Link>
                <div style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: "0.2rem" }}>
                  {sub.plan?.name ?? "—"} · {pl.main}
                  {pl.sub ? ` ${pl.sub}` : ""}
                  {sub.cancelAtPeriodEnd && <span style={{ color: "var(--danger)" }}> · ending</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                {sub.status === "ACTIVE" && (
                  <Link
                    className="btn"
                    href={`/agents/${sub.listing?.slug ?? ""}`}
                    style={{ padding: "0.45rem 0.8rem", whiteSpace: "nowrap", textDecoration: "none", fontSize: "0.85rem" }}
                  >
                    Connect
                  </Link>
                )}
                {!sub.cancelAtPeriodEnd && (
                  <button
                    className="btn btn-ghost"
                    style={{ padding: "0.45rem 0.8rem", whiteSpace: "nowrap" }}
                    onClick={() => cancel.mutate({ id: sub.id })}
                    disabled={cancel.isPending}
                  >
                    {cancel.isPending ? "…" : "Cancel"}
                  </button>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
