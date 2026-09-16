"use client";

/**
 * Seller onboarding — a 5-step flow that creates the seller profile AND their
 * first agent listing in one submission.
 *
 * Steps: 1) storefront  2) the agent  3) how it connects (MCP spec)
 *        4) pricing      5) review & submit
 *
 * State lives in one object; each step validates its slice against the shared
 * Zod schemas before letting the user advance, so bad data never reaches the
 * final mutation. The final submit calls seller.completeOnboarding.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { z } from "zod";
import { api } from "@/lib/trpc";
import {
  handleSchema,
  mcpSpecSchema,
  pricingPlanSchema,
} from "@/schemas";
import styles from "./onboarding.module.css";

type Transport = "STDIO" | "SSE" | "STREAMABLE_HTTP";
type AuthType = "NONE" | "API_KEY" | "OAUTH";
type PricingModel = "FREE" | "FLAT_RATE" | "USAGE";

interface FormState {
  // profile
  handle: string;
  displayName: string;
  bio: string;
  websiteUrl: string;
  // listing
  name: string;
  tagline: string;
  description: string;
  categorySlug: string;
  // mcp spec
  transport: Transport;
  endpointUrl: string;
  authType: AuthType;
  // pricing
  pricingModel: PricingModel;
  planName: string;
  priceDollars: string; // user types dollars; we convert to cents
  interval: "MONTH" | "YEAR";
  unitPriceCents: string;
  unitLabel: string;
}

const initial: FormState = {
  handle: "",
  displayName: "",
  bio: "",
  websiteUrl: "",
  name: "",
  tagline: "",
  description: "",
  categorySlug: "",
  transport: "STREAMABLE_HTTP",
  endpointUrl: "",
  authType: "NONE",
  pricingModel: "FREE",
  planName: "Free",
  priceDollars: "",
  interval: "MONTH",
  unitPriceCents: "",
  unitLabel: "per call",
};

const TOTAL_STEPS = 5;

export function OnboardingFlow() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormState>(initial);
  const [errors, setErrors] = useState<string[]>([]);

  const onboard = api.seller.completeOnboarding.useMutation({
    onSuccess: () => {
      // Land on the dashboard, refreshed so server sees the new seller.
      router.refresh();
      router.push("/dashboard");
    },
    onError: (e) => setErrors([e.message]),
  });

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  // Build the pricing plan object from the form for validation + submission.
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
    return base; // FREE
  }

  // Per-step validation. Returns true if the step is valid (and clears errors).
  function validateStep(s: number): boolean {
    const errs: string[] = [];

    if (s === 1) {
      const r = handleSchema.safeParse(form.handle);
      if (!r.success) errs.push(r.error.issues[0]?.message ?? "Invalid handle");
      if (form.displayName.trim().length < 2) errs.push("Display name is too short");
      if (form.websiteUrl && !z.string().url().safeParse(form.websiteUrl).success)
        errs.push("Website must be a valid URL");
    }

    if (s === 2) {
      if (form.name.trim().length < 3) errs.push("Agent name must be at least 3 characters");
      if (form.tagline.trim().length < 10) errs.push("Tagline must be at least 10 characters");
      if (form.description.trim().length < 30) errs.push("Description must be at least 30 characters");
    }

    if (s === 3) {
      const r = mcpSpecSchema.safeParse({
        transport: form.transport,
        endpointUrl: form.endpointUrl || undefined,
        authType: form.authType,
        capabilities: { tools: [] },
      });
      if (!r.success) errs.push(r.error.issues[0]?.message ?? "Invalid connection details");
    }

    if (s === 4) {
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
    // Final guard: re-validate every step before firing the mutation.
    for (let s = 1; s <= 4; s++) {
      if (!validateStep(s)) {
        setStep(s);
        return;
      }
    }
    onboard.mutate({
      profile: {
        handle: form.handle,
        displayName: form.displayName,
        bio: form.bio || undefined,
        websiteUrl: form.websiteUrl || undefined,
      },
      listing: {
        name: form.name,
        tagline: form.tagline,
        description: form.description,
        categorySlug: form.categorySlug || undefined,
        mcpSpec: {
          transport: form.transport,
          endpointUrl: form.endpointUrl || undefined,
          authType: form.authType,
          capabilities: { tools: [] },
        },
        plans: [buildPlan()],
      },
    });
  }

  return (
    <div className={styles.shell}>
      <div className={styles.topbar}>
        <Link href="/" className={styles.wordmark}>
          <span className={styles.bk}>[</span>ai<span className={styles.bk}>]</span> marketplace
        </Link>
        <Link href="/" style={{ fontSize: "0.9rem", color: "var(--muted)" }}>
          Cancel
        </Link>
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
            {errors.map((e, i) => (
              <div key={i}>{e}</div>
            ))}
          </div>
        )}

        {/* STEP 1 — storefront */}
        {step === 1 && (
          <>
            <p className={styles.eyebrow}>Step 1 of 5</p>
            <h2>Set up your storefront</h2>
            <p className={styles.lead}>This is how buyers will see you on the marketplace.</p>

            <div className="field">
              <label>Handle</label>
              <div className={styles.handleField}>
                <span className={styles.handlePrefix}>marketplace/sellers/</span>
                <input
                  value={form.handle}
                  onChange={(e) => set("handle", e.target.value.toLowerCase())}
                  placeholder="acme-ai"
                />
              </div>
              <span className="form-note">Lowercase letters, numbers, and hyphens.</span>
            </div>

            <div className="field">
              <label>Display name</label>
              <input value={form.displayName} onChange={(e) => set("displayName", e.target.value)} placeholder="Acme AI" />
            </div>

            <div className="field">
              <label>Bio <span style={{ color: "var(--muted)", fontWeight: 400 }}>(optional)</span></label>
              <textarea rows={3} value={form.bio} onChange={(e) => set("bio", e.target.value)} placeholder="What you build and why buyers should trust you." />
            </div>

            <div className="field">
              <label>Website <span style={{ color: "var(--muted)", fontWeight: 400 }}>(optional)</span></label>
              <input value={form.websiteUrl} onChange={(e) => set("websiteUrl", e.target.value)} placeholder="https://acme.ai" />
            </div>
          </>
        )}

        {/* STEP 2 — the agent */}
        {step === 2 && (
          <>
            <p className={styles.eyebrow}>Step 2 of 5</p>
            <h2>Describe your agent</h2>
            <p className={styles.lead}>Tell buyers what your MCP server or agent does.</p>

            <div className="field">
              <label>Name</label>
              <input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Inbox Triage Agent" />
            </div>
            <div className="field">
              <label>Tagline</label>
              <input value={form.tagline} onChange={(e) => set("tagline", e.target.value)} placeholder="Sorts and prioritizes your email automatically." />
              <span className="form-note">One line, shown on cards. 10–140 characters.</span>
            </div>
            <div className="field">
              <label>Description</label>
              <textarea rows={5} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="What it does, how it works, what tools it exposes…" />
            </div>
            <div className="field">
              <label>Category slug <span style={{ color: "var(--muted)", fontWeight: 400 }}>(optional)</span></label>
              <input value={form.categorySlug} onChange={(e) => set("categorySlug", e.target.value.toLowerCase())} placeholder="productivity" />
              <span className="form-note">We’ll match it to a category if it exists.</span>
            </div>
          </>
        )}

        {/* STEP 3 — connection */}
        {step === 3 && (
          <>
            <p className={styles.eyebrow}>Step 3 of 5</p>
            <h2>How it connects</h2>
            <p className={styles.lead}>The technical details buyers’ tools need to connect to your server.</p>

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

        {/* STEP 4 — pricing */}
        {step === 4 && (
          <>
            <p className={styles.eyebrow}>Step 4 of 5</p>
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
                      // Sensible default plan name per model.
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

        {/* STEP 5 — review */}
        {step === 5 && (
          <>
            <p className={styles.eyebrow}>Step 5 of 5</p>
            <h2>Review &amp; submit</h2>
            <p className={styles.lead}>Check everything over. You can edit your listing afterward from your dashboard.</p>

            <div className={styles.reviewBlock}>
              <h3>Storefront</h3>
              <div className={styles.kv}><span className="k">Handle</span><span className="v">{form.handle}</span></div>
              <div className={styles.kv}><span className="k">Display name</span><span className="v">{form.displayName}</span></div>
              {form.websiteUrl && <div className={styles.kv}><span className="k">Website</span><span className="v">{form.websiteUrl}</span></div>}
            </div>

            <div className={styles.reviewBlock}>
              <h3>Agent</h3>
              <div className={styles.kv}><span className="k">Name</span><span className="v">{form.name}</span></div>
              <div className={styles.kv}><span className="k">Tagline</span><span className="v">{form.tagline}</span></div>
              {form.categorySlug && <div className={styles.kv}><span className="k">Category</span><span className="v">{form.categorySlug}</span></div>}
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
                <div className={styles.kv}><span className="k">Price</span><span className="v">{form.unitPriceCents}¢ {form.unitLabel}</span></div>
              )}
            </div>

            <p className="form-note" style={{ marginTop: "0.75rem" }}>
              Your agent will be saved as a draft. From your dashboard you can submit it
              for review — our approval check looks it over before it goes live.
            </p>
          </>
        )}

        {/* Actions */}
        <div className={styles.actions}>
          {step > 1 ? (
            <button className="btn btn-ghost" onClick={back} disabled={onboard.isPending}>
              Back
            </button>
          ) : (
            <span className={styles.spacer} />
          )}
          <span className={styles.spacer} />
          {step < TOTAL_STEPS ? (
            <button className="btn" onClick={next}>
              Continue
            </button>
          ) : (
            <button className="btn" onClick={submit} disabled={onboard.isPending}>
              {onboard.isPending ? "Creating…" : "Create my listing"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
