"use client";

/**
 * Edit listing form — pre-fills from the existing listing and saves via
 * listing.update. Reuses the same field patterns and CSS tokens from the
 * onboarding flow. Steps: 1) agent  2) connection  3) pricing  4) review.
 *
 * If the listing was PUBLISHED or REJECTED, saving transitions it back to
 * DRAFT (re-review required).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/trpc";
import { mcpSpecSchema, pricingPlanSchema } from "@/schemas";
import styles from "@/app/sell/onboarding/onboarding.module.css";

type Transport = "STDIO" | "SSE" | "STREAMABLE_HTTP";
type AuthType = "NONE" | "API_KEY" | "OAUTH";
type PricingModel = "FREE" | "FLAT_RATE" | "USAGE";

interface FormState {
  name: string;
  tagline: string;
  description: string;
  transport: Transport;
  endpointUrl: string;
  authType: AuthType;
  pricingModel: PricingModel;
  planName: string;
  priceDollars: string;
  interval: "MONTH" | "YEAR";
  unitPriceCents: string;
  unitLabel: string;
}

const TOTAL_STEPS = 4;

export function EditListingForm({ listingId }: { listingId: string }) {
  const router = useRouter();
  const { data: listing, isLoading } = api.listing.byId.useQuery({ id: listingId });

  const [initialized, setInitialized] = useState(false);
  const [step, setStep] = useState(1);
  const [errors, setErrors] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  const [form, setForm] = useState<FormState>({
    name: "",
    tagline: "",
    description: "",
    transport: "STREAMABLE_HTTP",
    endpointUrl: "",
    authType: "NONE",
    pricingModel: "FREE",
    planName: "Free",
    priceDollars: "",
    interval: "MONTH",
    unitPriceCents: "",
    unitLabel: "per call",
  });

  // Pre-fill form once listing loads.
  if (listing && !initialized) {
    const plan = listing.plans?.[0];
    const pricingModel = (plan?.model ?? "FREE") as PricingModel;
    setForm({
      name: listing.name,
      tagline: listing.tagline,
      description: listing.description,
      transport: (listing.mcpSpec?.transport ?? "STREAMABLE_HTTP") as Transport,
      endpointUrl: listing.mcpSpec?.endpointUrl ?? "",
      authType: (listing.mcpSpec?.authType ?? "NONE") as AuthType,
      pricingModel,
      planName: plan?.name ?? "Free",
      priceDollars: plan?.priceCents ? (plan.priceCents / 100).toString() : "",
      interval: (plan?.interval ?? "MONTH") as "MONTH" | "YEAR",
      unitPriceCents: plan?.unitPriceCents?.toString() ?? "",
      unitLabel: plan?.unitLabel ?? "per call",
    });
    setInitialized(true);
  }

  const update = api.listing.update.useMutation({
    onSuccess: (res) => {
      if (res.statusChanged) {
        setSaved(true);
      } else {
        router.push("/dashboard");
      }
    },
    onError: (e) => setErrors([e.message]),
  });

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function buildPlan() {
    const base = { name: form.planName, model: form.pricingModel, currency: "usd" as const };
    if (form.pricingModel === "FLAT_RATE") {
      const cents = Math.round(parseFloat(form.priceDollars || "0") * 100);
      return { ...base, priceCents: cents, interval: form.interval };
    }
    if (form.pricingModel === "USAGE") {
      return {
        ...base,
        unitPriceCents: parseInt(form.unitPriceCents || "0", 10),
        unitLabel: form.unitLabel,
      };
    }
    return base;
  }

  function validateStep(s: number): boolean {
    const errs: string[] = [];
    if (s === 1) {
      if (form.name.trim().length < 3) errs.push("Agent name must be at least 3 characters");
      if (form.tagline.trim().length < 10) errs.push("Tagline must be at least 10 characters");
      if (form.description.trim().length < 30) errs.push("Description must be at least 30 characters");
    }
    if (s === 2) {
      const r = mcpSpecSchema.safeParse({
        transport: form.transport,
        endpointUrl: form.endpointUrl || undefined,
        authType: form.authType,
        capabilities: { tools: [] },
      });
      if (!r.success) errs.push(r.error.issues[0]?.message ?? "Invalid connection details");
    }
    if (s === 3) {
      const r = pricingPlanSchema.safeParse(buildPlan());
      if (!r.success) errs.push(r.error.issues[0]?.message ?? "Invalid pricing");
    }
    setErrors(errs);
    return errs.length === 0;
  }

  function next() {
    if (validateStep(step)) setStep((s) => Math.min(s + 1, TOTAL_STEPS));
  }
  function back() {
    setErrors([]);
    setStep((s) => Math.max(s - 1, 1));
  }

  function submit() {
    for (let s = 1; s <= 3; s++) {
      if (!validateStep(s)) { setStep(s); return; }
    }
    update.mutate({
      id: listingId,
      name: form.name,
      tagline: form.tagline,
      description: form.description,
      mcpSpec: {
        transport: form.transport,
        endpointUrl: form.endpointUrl || undefined,
        authType: form.authType,
        capabilities: { tools: [] },
      },
      plans: [buildPlan()],
    });
  }

  if (isLoading || !initialized) {
    return (
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <Link href="/dashboard" className={styles.wordmark}>
            <span className={styles.bk}>[</span>ai<span className={styles.bk}>]</span> marketplace
          </Link>
        </div>
        <div className={styles.card}>
          <p style={{ color: "var(--muted)" }}>Loading listing...</p>
        </div>
      </div>
    );
  }

  if (saved) {
    return (
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <Link href="/dashboard" className={styles.wordmark}>
            <span className={styles.bk}>[</span>ai<span className={styles.bk}>]</span> marketplace
          </Link>
        </div>
        <div className={styles.card}>
          <div className={styles.successWrap}>
            <div className={styles.big}>!</div>
            <h2>Changes saved</h2>
            <p style={{ color: "var(--muted)", margin: "0.5rem 0 1.25rem" }}>
              Your changes mean this listing needs re-review — submit it again from your dashboard.
            </p>
            <Link className="btn" href="/dashboard">Back to dashboard</Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      <div className={styles.topbar}>
        <Link href="/dashboard" className={styles.wordmark}>
          <span className={styles.bk}>[</span>ai<span className={styles.bk}>]</span> marketplace
        </Link>
        <Link href="/dashboard" style={{ fontSize: "0.9rem", color: "var(--muted)" }}>Cancel</Link>
      </div>

      <div className={styles.stepper} aria-hidden>
        {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
          <div
            key={i}
            className={`${styles.step} ${i + 1 < step ? styles.done : ""} ${i + 1 === step ? styles.active : ""}`}
          />
        ))}
      </div>

      <div className={styles.card}>
        {errors.length > 0 && (
          <div className="form-error">
            {errors.map((e, i) => <div key={i}>{e}</div>)}
          </div>
        )}

        {step === 1 && (
          <>
            <p className={styles.eyebrow}>Step 1 of {TOTAL_STEPS}</p>
            <h2>Edit your agent</h2>
            <p className={styles.lead}>Update the details buyers see about your MCP server.</p>

            <div className="field">
              <label>Name</label>
              <input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Inbox Triage Agent" />
            </div>
            <div className="field">
              <label>Tagline</label>
              <input value={form.tagline} onChange={(e) => set("tagline", e.target.value)} placeholder="Sorts and prioritizes your email automatically." />
              <span className="form-note">One line, shown on cards. 10-140 characters.</span>
            </div>
            <div className="field">
              <label>Description</label>
              <textarea rows={5} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="What it does, how it works, what tools it exposes..." />
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <p className={styles.eyebrow}>Step 2 of {TOTAL_STEPS}</p>
            <h2>How it connects</h2>
            <p className={styles.lead}>The technical details buyers' tools need to connect to your server.</p>

            <div className="field">
              <label>Transport</label>
              <select value={form.transport} onChange={(e) => set("transport", e.target.value as Transport)}>
                <option value="STREAMABLE_HTTP">Streamable HTTP (remote — recommended)</option>
                <option value="SSE">SSE (remote, legacy)</option>
                <option value="STDIO">stdio (local process)</option>
              </select>
            </div>
            {form.transport !== "STDIO" && (
              <div className="field">
                <label>Endpoint URL</label>
                <input value={form.endpointUrl} onChange={(e) => set("endpointUrl", e.target.value)} placeholder="https://api.acme.ai/mcp" />
                <span className="form-note">Where the server is reachable.</span>
              </div>
            )}
            <div className="field">
              <label>Authentication</label>
              <select value={form.authType} onChange={(e) => set("authType", e.target.value as AuthType)}>
                <option value="NONE">None (open server)</option>
                <option value="API_KEY">API key (buyers get a key on subscribe)</option>
                <option value="OAUTH">OAuth</option>
              </select>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <p className={styles.eyebrow}>Step 3 of {TOTAL_STEPS}</p>
            <h2>Set your pricing</h2>
            <p className={styles.lead}>How buyers pay to use your agent.</p>

            <div className={styles.choices}>
              {([
                ["FREE", "Free", "No charge. Good for getting traction."],
                ["FLAT_RATE", "Subscription", "A fixed price billed monthly or yearly."],
                ["USAGE", "Usage-based", "Charge per call or per unit of use."],
              ] as const).map(([val, title, desc]) => (
                <label key={val} className={`${styles.choice} ${form.pricingModel === val ? styles.selected : ""}`}>
                  <input
                    type="radio"
                    name="pricing"
                    checked={form.pricingModel === val}
                    onChange={() => {
                      set("pricingModel", val);
                      set("planName", val === "FREE" ? "Free" : val === "FLAT_RATE" ? "Pro" : "Metered");
                    }}
                  />
                  <div>
                    <div className={styles.ctitle}>{title}</div>
                    <div className={styles.cdesc}>{desc}</div>
                  </div>
                </label>
              ))}
            </div>

            <div className="field">
              <label>Plan name</label>
              <input value={form.planName} onChange={(e) => set("planName", e.target.value)} />
            </div>

            {form.pricingModel === "FLAT_RATE" && (
              <div className={styles.row2}>
                <div className="field">
                  <label>Price (USD)</label>
                  <input value={form.priceDollars} onChange={(e) => set("priceDollars", e.target.value)} placeholder="19.99" inputMode="decimal" />
                </div>
                <div className="field">
                  <label>Billing interval</label>
                  <select value={form.interval} onChange={(e) => set("interval", e.target.value as "MONTH" | "YEAR")}>
                    <option value="MONTH">Monthly</option>
                    <option value="YEAR">Yearly</option>
                  </select>
                </div>
              </div>
            )}

            {form.pricingModel === "USAGE" && (
              <div className={styles.row2}>
                <div className="field">
                  <label>Price per unit (cents)</label>
                  <input value={form.unitPriceCents} onChange={(e) => set("unitPriceCents", e.target.value)} placeholder="5" inputMode="numeric" />
                </div>
                <div className="field">
                  <label>Unit label</label>
                  <input value={form.unitLabel} onChange={(e) => set("unitLabel", e.target.value)} placeholder="per call" />
                </div>
              </div>
            )}
          </>
        )}

        {step === 4 && (
          <>
            <p className={styles.eyebrow}>Step 4 of {TOTAL_STEPS}</p>
            <h2>Review your changes</h2>
            <p className={styles.lead}>
              {listing && (listing.status === "PUBLISHED" || listing.status === "REJECTED")
                ? "Saving will move this listing back to draft — you'll need to re-submit it for review."
                : "Check everything over before saving."}
            </p>

            <div className={styles.reviewBlock}>
              <h3>Agent</h3>
              <div className={styles.kv}><span className="k">Name</span><span className="v">{form.name}</span></div>
              <div className={styles.kv}><span className="k">Tagline</span><span className="v">{form.tagline}</span></div>
            </div>

            <div className={styles.reviewBlock}>
              <h3>Connection</h3>
              <div className={styles.kv}><span className="k">Transport</span><span className="v">{form.transport}</span></div>
              {form.endpointUrl && <div className={styles.kv}><span className="k">Endpoint</span><span className="v">{form.endpointUrl}</span></div>}
              <div className={styles.kv}><span className="k">Auth</span><span className="v">{form.authType}</span></div>
            </div>

            <div className={styles.reviewBlock}>
              <h3>Pricing</h3>
              <div className={styles.kv}><span className="k">Model</span><span className="v">{form.pricingModel}</span></div>
              <div className={styles.kv}><span className="k">Plan</span><span className="v">{form.planName}</span></div>
              {form.pricingModel === "FLAT_RATE" && (
                <div className={styles.kv}><span className="k">Price</span><span className="v">${form.priceDollars}/{form.interval === "MONTH" ? "mo" : "yr"}</span></div>
              )}
              {form.pricingModel === "USAGE" && (
                <div className={styles.kv}><span className="k">Price</span><span className="v">{form.unitPriceCents}c {form.unitLabel}</span></div>
              )}
            </div>
          </>
        )}

        <div className={styles.actions}>
          {step > 1 ? (
            <button className="btn btn-ghost" onClick={back} disabled={update.isPending}>Back</button>
          ) : (
            <span className={styles.spacer} />
          )}
          <span className={styles.spacer} />
          {step < TOTAL_STEPS ? (
            <button className="btn" onClick={next}>Continue</button>
          ) : (
            <button className="btn" onClick={submit} disabled={update.isPending}>
              {update.isPending ? "Saving..." : "Save changes"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
