"use client";

/**
 * Escalation queue UI. Lists escalated listings; clicking one expands the full
 * review detail (the agent's reasoning, risk flags, the spec) with Approve /
 * Decline actions that resolve the escalation.
 */
import { useState } from "react";
import { api } from "@/lib/trpc";

interface RiskFlag {
  code: string;
  detail: string;
  severity: "low" | "medium" | "high";
}

interface ProbeResultData {
  reachable: boolean;
  probedTools: string[] | null;
  mismatch: { undeclared: string[]; missing: string[] } | null;
  error: string | null;
  sensitiveUndeclared: string[];
}

function ReviewDetail({ id, onResolved }: { id: string; onResolved: () => void }) {
  const { data, isLoading } = api.admin.reviewDetail.useQuery({ id });
  const utils = api.useUtils();
  const [note, setNote] = useState("");

  const resolve = api.admin.resolve.useMutation({
    onSuccess: () => {
      utils.admin.escalationQueue.invalidate();
      onResolved();
    },
  });

  if (isLoading || !data) return <p style={{ color: "var(--muted)", padding: "0.75rem 0" }}>Loading…</p>;

  const latest = data.listingReviews?.[0];
  const flags: RiskFlag[] = Array.isArray(latest?.riskFlags) ? (latest!.riskFlags as unknown as RiskFlag[]) : [];

  const sevColor = { low: "#8a5a12", medium: "#8a5a12", high: "var(--danger)" } as const;

  return (
    <div style={{ borderTop: "1px solid var(--line)", marginTop: "0.9rem", paddingTop: "0.9rem" }}>
      <div style={{ display: "grid", gap: "0.9rem" }}>
        <div>
          <div style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", marginBottom: "0.3rem" }}>Description</div>
          <div style={{ fontSize: "0.9rem", color: "var(--ink-soft)", whiteSpace: "pre-wrap" }}>{data.description}</div>
        </div>

        <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: "0.85rem" }}>
          <div><span style={{ color: "var(--muted)" }}>Transport: </span><strong>{data.mcpSpec?.transport ?? "—"}</strong></div>
          <div><span style={{ color: "var(--muted)" }}>Auth: </span><strong>{data.mcpSpec?.authType ?? "—"}</strong></div>
          {data.mcpSpec?.endpointUrl && <div><span style={{ color: "var(--muted)" }}>Endpoint: </span><strong>{data.mcpSpec.endpointUrl}</strong></div>}
        </div>

        {latest?.reasoning && (
          <div style={{ background: "var(--paper-tint)", borderRadius: "var(--radius)", padding: "0.75rem 0.9rem" }}>
            <div style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", marginBottom: "0.3rem" }}>
              Agent reasoning {typeof latest.riskScore === "number" && <>· risk {latest.riskScore}/100</>}
            </div>
            <div style={{ fontSize: "0.88rem", color: "var(--ink-soft)" }}>{latest.reasoning}</div>
            {flags.length > 0 && (
              <ul style={{ margin: "0.6rem 0 0", padding: 0, listStyle: "none", display: "grid", gap: "0.3rem" }}>
                {flags.map((f, i) => (
                  <li key={i} style={{ fontSize: "0.82rem" }}>
                    <span style={{ color: sevColor[f.severity], fontWeight: 600 }}>[{f.severity}]</span>{" "}
                    <span style={{ color: "var(--ink-soft)" }}>{f.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {latest?.probeResult && (() => {
          const probe = latest.probeResult as unknown as ProbeResultData;
          return (
            <div style={{ background: "var(--paper-tint)", borderRadius: "var(--radius)", padding: "0.75rem 0.9rem" }}>
              <div style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", marginBottom: "0.3rem" }}>
                Capability probe
              </div>
              <div style={{ fontSize: "0.85rem", display: "grid", gap: "0.4rem" }}>
                <div>
                  <span style={{ color: "var(--muted)" }}>Reachable: </span>
                  <strong style={{ color: probe.reachable ? "var(--success, #16a34a)" : "var(--muted)" }}>
                    {probe.reachable ? "Yes" : "No"}
                  </strong>
                  {probe.error && <span style={{ color: "var(--ink-soft)", marginLeft: "0.5rem" }}>({probe.error})</span>}
                </div>
                {probe.probedTools && (
                  <div>
                    <span style={{ color: "var(--muted)" }}>Probed tools ({probe.probedTools.length}): </span>
                    <span style={{ color: "var(--ink-soft)" }}>{probe.probedTools.join(", ") || "none"}</span>
                  </div>
                )}
                {probe.mismatch && (
                  <>
                    {probe.mismatch.undeclared.length > 0 && (
                      <div>
                        <span style={{ color: "#8a5a12", fontWeight: 600 }}>Undeclared: </span>
                        <span style={{ color: "var(--ink-soft)" }}>{probe.mismatch.undeclared.join(", ")}</span>
                      </div>
                    )}
                    {probe.mismatch.missing.length > 0 && (
                      <div>
                        <span style={{ color: "var(--muted)", fontWeight: 600 }}>Missing: </span>
                        <span style={{ color: "var(--ink-soft)" }}>{probe.mismatch.missing.join(", ")}</span>
                      </div>
                    )}
                  </>
                )}
                {probe.sensitiveUndeclared.length > 0 && (
                  <div>
                    <span style={{ color: "var(--danger)", fontWeight: 600 }}>Sensitive undeclared: </span>
                    <span style={{ color: "var(--danger)" }}>{probe.sensitiveUndeclared.join(", ")}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        <div className="field" style={{ marginBottom: 0 }}>
          <label>Note <span style={{ color: "var(--muted)", fontWeight: 400 }}>(optional, saved with your decision)</span></label>
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why you're approving or declining." />
        </div>

        <div style={{ display: "flex", gap: "0.6rem" }}>
          <button
            className="btn"
            onClick={() => resolve.mutate({ id, decision: "APPROVED", note: note || undefined })}
            disabled={resolve.isPending}
          >
            {resolve.isPending ? "Saving…" : "Approve & publish"}
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => resolve.mutate({ id, decision: "REJECTED", note: note || undefined })}
            disabled={resolve.isPending}
          >
            Decline
          </button>
        </div>
      </div>
    </div>
  );
}

export function EscalationQueue() {
  const { data, isLoading, error } = api.admin.escalationQueue.useQuery();
  const [openId, setOpenId] = useState<string | null>(null);

  if (isLoading) return <p style={{ color: "var(--muted)" }}>Loading the queue…</p>;
  if (error) return <p style={{ color: "var(--danger)" }}>Couldn’t load: {error.message}</p>;
  if (!data || data.length === 0) {
    return (
      <div style={{ padding: "2rem", border: "1px dashed var(--line-strong)", borderRadius: "var(--radius-lg)", background: "var(--paper)", color: "var(--muted)" }}>
        Nothing waiting. The queue is clear.
      </div>
    );
  }

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.75rem" }}>
      {data.map((item) => (
        <li key={item.id} style={{ padding: "1.1rem 1.2rem", border: "1px solid var(--line)", borderRadius: "var(--radius-lg)", background: "var(--paper)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", cursor: "pointer" }} onClick={() => setOpenId(openId === item.id ? null : item.id)}>
            <div>
              <div style={{ fontWeight: 600 }}>{item.name}</div>
              <div style={{ color: "var(--ink-soft)", fontSize: "0.9rem", marginTop: "0.15rem" }}>{item.tagline}</div>
              <div style={{ color: "var(--muted)", fontSize: "0.82rem", marginTop: "0.4rem" }}>
                by {item.seller?.displayName ?? "Unknown"}
                {typeof item.riskScore === "number" && ` · risk ${item.riskScore}/100`}
              </div>
            </div>
            <button className="btn btn-ghost" style={{ padding: "0.4rem 0.8rem", whiteSpace: "nowrap" }}>
              {openId === item.id ? "Close" : "Review"}
            </button>
          </div>
          {openId === item.id && <ReviewDetail id={item.id} onResolved={() => setOpenId(null)} />}
        </li>
      ))}
    </ul>
  );
}
