"use client";

/**
 * Subscribe panel — plan selection + the subscribe action. Free plans subscribe
 * immediately (the server grants access). Paid plans currently hit the Stripe
 * integration point, which isn't wired yet — we surface that honestly rather
 * than faking a purchase. Signed-out users are sent to sign in first.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/trpc";
import { priceLabel } from "@/lib/listing-format";
import { ConnectPanel } from "./connect";

interface Plan {
  id: string;
  name: string;
  model: "FREE" | "FLAT_RATE" | "USAGE";
  priceCents?: number | null;
  currency?: string;
  interval?: "MONTH" | "YEAR" | null;
  unitPriceCents?: number | null;
  unitLabel?: string | null;
}

export function SubscribePanel({ listingId, plans }: { listingId: string; plans: Plan[] }) {
  const router = useRouter();
  const [selected, setSelected] = useState(plans[0]?.id ?? "");
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "info"; text: string } | null>(null);

  // Check if already subscribed. Error is expected for signed-out users.
  const { data: subStatus } = api.subscription.statusForListing.useQuery(
    { listingId },
    { retry: false },
  );

  const utils = api.useUtils();
  const subscribe = api.subscription.create.useMutation({
    onSuccess: (data) => {
      // Paid plans return a Stripe Checkout URL — redirect the browser.
      if (data && typeof data === "object" && "checkoutUrl" in data && data.checkoutUrl) {
        window.location.href = data.checkoutUrl as string;
        return;
      }
      // Free plans are immediately active — refresh subscription status.
      utils.subscription.statusForListing.invalidate({ listingId });
      setMsg({ kind: "ok", text: "You’re subscribed! Connection details are below." });
    },
    onError: (e) => {
      if (e.data?.code === "UNAUTHORIZED") {
        router.push("/sign-in");
        return;
      }
      setMsg({ kind: "err", text: e.message });
    },
  });

  // Show the connect panel if already subscribed.
  if (subStatus?.active) {
    return <ConnectPanel listingId={listingId} />;
  }

  if (plans.length === 0) {
    return <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>No plans available.</p>;
  }

  const selectedPlan = plans.find((p) => p.id === selected);

  return (
    <div>
      {plans.length > 1 && (
        <div style={{ display: "grid", gap: "0.4rem", marginBottom: "0.8rem" }}>
          {plans.map((p) => {
            const pl = priceLabel([p]);
            return (
              <label
                key={p.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "0.6rem",
                  padding: "0.55rem 0.7rem",
                  border: `1px solid ${selected === p.id ? "var(--accent)" : "var(--line-strong)"}`,
                  background: selected === p.id ? "var(--accent-tint)" : "var(--paper)",
                  borderRadius: "var(--radius)",
                  cursor: "pointer",
                  fontSize: "0.88rem",
                }}
              >
                <span style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="radio" name="plan" checked={selected === p.id} onChange={() => setSelected(p.id)} />
                  {p.name}
                </span>
                <span style={{ fontWeight: 600 }}>
                  {pl.main}
                  {pl.sub && <span style={{ fontWeight: 400, color: "var(--muted)" }}> {pl.sub}</span>}
                </span>
              </label>
            );
          })}
        </div>
      )}

      <button
        className="btn"
        style={{ width: "100%" }}
        disabled={subscribe.isPending || !selected}
        onClick={() => {
          setMsg(null);
          subscribe.mutate({ listingId, planId: selected });
        }}
      >
        {subscribe.isPending
          ? "Working…"
          : selectedPlan?.model === "FREE"
            ? "Get it free"
            : "Subscribe"}
      </button>

      {msg && (
        <div
          style={{
            marginTop: "0.7rem",
            padding: "0.6rem 0.7rem",
            borderRadius: "var(--radius)",
            fontSize: "0.82rem",
            background:
              msg.kind === "ok" ? "var(--accent-tint)" : msg.kind === "err" ? "var(--danger-tint)" : "var(--paper-tint)",
            color: msg.kind === "err" ? "var(--danger)" : msg.kind === "ok" ? "var(--accent)" : "var(--ink-soft)",
          }}
        >
          {msg.text}
        </div>
      )}

      <p style={{ fontSize: "0.78rem", color: "var(--muted)", textAlign: "center", marginTop: "0.7rem" }}>
        Cancel anytime.
      </p>
    </div>
  );
}
