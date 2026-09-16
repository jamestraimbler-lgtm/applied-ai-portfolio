"use client";

/**
 * Payouts section on the seller dashboard — shows payout status and a button
 * to start or continue Stripe Connect onboarding.
 */
import { api } from "@/lib/trpc";

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  NOT_STARTED: { label: "Not started", color: "var(--muted)" },
  PENDING: { label: "Pending verification", color: "#8a5a12" },
  ACTIVE: { label: "Active", color: "var(--success)" },
  RESTRICTED: { label: "Restricted", color: "var(--danger)" },
};

export function PayoutsSection() {
  const { data: seller, isLoading } = api.seller.me.useQuery();

  const startOnboarding = api.seller.startPayoutOnboarding.useMutation({
    onSuccess: (data) => {
      window.location.href = data.url;
    },
  });

  const refreshStatus = api.seller.refreshPayoutStatus.useMutation({
    onSuccess: () => {
      // Refetch seller profile to update UI.
      void utils.seller.me.invalidate();
    },
  });

  const utils = api.useUtils();

  if (isLoading || !seller) return null;

  const status = STATUS_LABEL[seller.payoutStatus] ?? STATUS_LABEL.NOT_STARTED!;
  const needsSetup = seller.payoutStatus === "NOT_STARTED" || seller.payoutStatus === "PENDING";

  return (
    <section
      style={{
        padding: "1.1rem 1.2rem",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-lg)",
        background: "var(--paper)",
        marginBottom: "1.5rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
        <div>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, margin: "0 0 0.2rem" }}>Payouts</h2>
          <p style={{ margin: 0, fontSize: "0.85rem", color: status.color, fontWeight: 500 }}>
            {status.label}
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {seller.payoutStatus === "ACTIVE" ? (
            <button
              className="btn btn-ghost"
              style={{ padding: "0.45rem 0.8rem", fontSize: "0.85rem" }}
              onClick={() => refreshStatus.mutate()}
              disabled={refreshStatus.isPending}
            >
              {refreshStatus.isPending ? "Checking…" : "Refresh status"}
            </button>
          ) : (
            <>
              <button
                className="btn"
                style={{ padding: "0.45rem 0.8rem", fontSize: "0.85rem" }}
                onClick={() => startOnboarding.mutate()}
                disabled={startOnboarding.isPending}
              >
                {startOnboarding.isPending
                  ? "Redirecting…"
                  : needsSetup
                    ? seller.payoutStatus === "NOT_STARTED"
                      ? "Set up payouts"
                      : "Continue setup"
                    : "Update payout info"}
              </button>
              {seller.payoutStatus === "PENDING" && (
                <button
                  className="btn btn-ghost"
                  style={{ padding: "0.45rem 0.8rem", fontSize: "0.85rem" }}
                  onClick={() => refreshStatus.mutate()}
                  disabled={refreshStatus.isPending}
                >
                  {refreshStatus.isPending ? "Checking…" : "Refresh"}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {startOnboarding.error && (
        <p style={{ margin: "0.5rem 0 0", fontSize: "0.82rem", color: "var(--danger)" }}>
          {startOnboarding.error.message}
        </p>
      )}
    </section>
  );
}
