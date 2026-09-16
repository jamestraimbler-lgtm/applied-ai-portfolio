/**
 * Approval agent — evaluates a listing and returns a structured verdict.
 *
 * ARCHITECTURE: the evaluator is swappable. Today it's a rules-based stub
 * (`ruleBasedEvaluator`) so the whole review pipeline works with no API key,
 * no cost, no latency. Later, drop in `claudeEvaluator` (a single function that
 * calls the Anthropic API) and NOTHING else changes — the verdict routing,
 * the DB writes, and the PUBLISHED-only-via-APPROVED invariant all live in the
 * router, not here.
 *
 * The evaluator's ONLY job: given listing + spec data, return an AgentVerdict
 * { verdict, reasoning, riskFlags, riskScore }. It must never touch the DB or
 * decide what status the listing ends up in — that's the router's job.
 *
 * Every listing passes through this on submit — onboarding's first listing AND
 * every later one. There is no path to PUBLISHED that skips it.
 */
import type { AgentVerdict, ProbeResult } from "@/schemas";
import { agentVerdictSchema } from "@/schemas";

/** The data the evaluator sees about a listing under review. */
export interface ReviewInput {
  name: string;
  tagline: string;
  description: string;
  pricing: Array<{
    model: "FREE" | "FLAT_RATE" | "USAGE";
    priceCents: number | null;
    unitPriceCents: number | null;
  }>;
  mcpSpec: {
    transport: "STDIO" | "SSE" | "STREAMABLE_HTTP";
    endpointUrl: string | null;
    authType: "NONE" | "API_KEY" | "OAUTH";
    // capabilities JSON (validated upstream); shape: { tools: [{name, description?}], ... }
    capabilities: unknown;
  } | null;
}

const MODEL_ID = "rules-based-stub-v1";

// ---------------------------------------------------------------------------
//  Heuristics used by the stub. Tuned to be cautious: it ESCALATES when unsure
//  rather than approving blindly, because the cost of a bad listing going live
//  is higher than the cost of a human glancing at an edge case.
// ---------------------------------------------------------------------------

// Phrases that signal scammy / misleading marketing claims.
const SCAM_PHRASES = [
  "guaranteed",
  "100x",
  "1000x",
  "get rich",
  "risk free",
  "risk-free",
  "no risk",
  "double your",
  "triple your",
  "instant money",
  "free money",
  "guaranteed profit",
  "guaranteed returns",
  "act now",
  "limited time",
  "once in a lifetime",
];

// Words hinting the server wants sensitive access — not disqualifying, but
// raises scrutiny (a credential-harvesting tool would describe itself this way).
const SENSITIVE_ACCESS = [
  "password",
  "credentials",
  "private key",
  "seed phrase",
  "ssn",
  "social security",
  "credit card",
  "bank account",
  "exfiltrate",
  "keylog",
  "scrape personal",
];

// Impersonation signals — claiming to be an official thing it likely isn't.
const IMPERSONATION = ["official openai", "official anthropic", "official google", "verified by"];

interface Signal {
  code: string;
  detail: string;
  severity: "low" | "medium" | "high";
}

function scan(haystack: string, needles: string[]): string[] {
  const lower = haystack.toLowerCase();
  return needles.filter((n) => lower.includes(n));
}

/**
 * Rules-based evaluator. Deterministic, cheap, and cautious. Produces the same
 * AgentVerdict shape the real Claude evaluator will.
 */
export function ruleBasedEvaluator(input: ReviewInput, probeResult?: ProbeResult | null): AgentVerdict {
  const flags: Signal[] = [];
  const text = `${input.name}\n${input.tagline}\n${input.description}`;

  // 1) Scammy marketing claims -> high severity.
  const scam = scan(text, SCAM_PHRASES);
  for (const phrase of scam) {
    flags.push({
      code: "MISLEADING_CLAIM",
      detail: `Contains a high-pressure or unrealistic claim: "${phrase}".`,
      severity: "high",
    });
  }

  // 2) Sensitive-access language -> medium (needs a human look).
  const sensitive = scan(text, SENSITIVE_ACCESS);
  for (const phrase of sensitive) {
    flags.push({
      code: "SENSITIVE_DATA_ACCESS",
      detail: `Mentions sensitive data/access: "${phrase}".`,
      severity: "medium",
    });
  }

  // 3) Impersonation -> high.
  const imp = scan(text, IMPERSONATION);
  for (const phrase of imp) {
    flags.push({
      code: "POSSIBLE_IMPERSONATION",
      detail: `May falsely claim official status: "${phrase}".`,
      severity: "high",
    });
  }

  // 4) Thin description -> low (quality signal, not a safety one).
  if (input.description.trim().length < 80) {
    flags.push({
      code: "THIN_DESCRIPTION",
      detail: "Description is very short; buyers may lack context to trust it.",
      severity: "low",
    });
  }

  // 5) Remote server with no auth -> low/medium depending on phrasing. A public
  //    open endpoint isn't inherently bad, but combined with sensitive language
  //    it's worth a human look.
  if (input.mcpSpec && input.mcpSpec.transport !== "STDIO" && input.mcpSpec.authType === "NONE") {
    flags.push({
      code: "OPEN_REMOTE_ENDPOINT",
      detail: "Remote server exposes tools with no authentication.",
      severity: sensitive.length > 0 ? "high" : "low",
    });
  }

  // 6) Missing spec entirely -> can't assess what it connects to.
  if (!input.mcpSpec) {
    flags.push({
      code: "MISSING_SPEC",
      detail: "No connection spec to evaluate.",
      severity: "medium",
    });
  }

  // 7) Probe-based signals — real network verification of the MCP endpoint.
  if (probeResult) {
    if (probeResult.sensitiveUndeclared.length > 0) {
      for (const tool of probeResult.sensitiveUndeclared) {
        flags.push({
          code: "SENSITIVE_UNDECLARED_TOOL",
          detail: `Server exposes undeclared sensitive tool: ${tool}`,
          severity: "high",
        });
      }
    }
    if (
      probeResult.mismatch?.undeclared &&
      probeResult.mismatch.undeclared.length > 0
    ) {
      // Only flag non-sensitive undeclared tools here (sensitive ones already flagged above)
      const nonSensitiveUndeclared = probeResult.mismatch.undeclared.filter(
        (t) => !probeResult.sensitiveUndeclared.includes(t),
      );
      if (nonSensitiveUndeclared.length > 0) {
        flags.push({
          code: "UNDECLARED_TOOLS",
          detail: `Server exposes ${nonSensitiveUndeclared.length} tools not in the listing`,
          severity: "medium",
        });
      }
    }
    if (probeResult.mismatch?.missing && probeResult.mismatch.missing.length > 0) {
      flags.push({
        code: "MISSING_CLAIMED_TOOLS",
        detail: `Listing claims tools the server doesn't expose: ${probeResult.mismatch.missing.join(", ")}`,
        severity: "low",
      });
    }
    if (!probeResult.reachable && probeResult.error) {
      flags.push({
        code: "PROBE_UNREACHABLE",
        detail: `Couldn't verify the server's tools: ${probeResult.error}`,
        severity: "medium",
      });
    }
  }

  // --- Score + verdict ---------------------------------------------------
  // Risk score: weighted sum of flag severities, capped at 100.
  const weight = { low: 8, medium: 22, high: 45 } as const;
  const riskScore = Math.min(
    100,
    flags.reduce((sum, f) => sum + weight[f.severity], 0),
  );

  const hasHigh = flags.some((f) => f.severity === "high");
  const hasMedium = flags.some((f) => f.severity === "medium");

  let verdict: AgentVerdict["verdict"];
  let reasoning: string;

  if (hasHigh) {
    // Any high-severity flag -> reject. These are the clear-cut bad cases.
    verdict = "REJECTED";
    reasoning =
      "Automatically declined due to high-risk signals: " +
      flags
        .filter((f) => f.severity === "high")
        .map((f) => f.detail)
        .join(" ") +
      " Please revise and resubmit.";
  } else if (hasMedium) {
    // Medium signals are ambiguous -> escalate to a human rather than guess.
    verdict = "ESCALATED";
    reasoning =
      "Flagged for human review due to signals that need judgment: " +
      flags
        .filter((f) => f.severity === "medium")
        .map((f) => f.detail)
        .join(" ");
  } else {
    // Only low/no flags -> approve.
    verdict = "APPROVED";
    reasoning =
      flags.length === 0
        ? "No risk signals detected. Listing meets the automated bar for publication."
        : "Minor quality notes only; cleared for publication: " +
          flags.map((f) => f.detail).join(" ");
  }

  // Validate our own output against the shared schema (defensive: guarantees the
  // router always receives a well-formed verdict, same as the real evaluator).
  return agentVerdictSchema.parse({
    verdict,
    reasoning,
    riskFlags: flags,
    riskScore,
  });
}

/**
 * The active evaluator. Swap this to `claudeEvaluator` to use real Claude.
 *
 * When wiring Claude later, that function will:
 *   1. Build a prompt from ReviewInput describing the review task + policy.
 *   2. Ask Claude to return ONLY JSON matching agentVerdictSchema.
 *   3. Parse + validate with agentVerdictSchema (reject/escalate on parse fail).
 * The signature stays identical, so the router doesn't change.
 */
export async function evaluateListing(
  input: ReviewInput,
  probeResult?: ProbeResult | null,
): Promise<{
  verdict: AgentVerdict;
  modelId: string;
}> {
  // Stub is synchronous; wrap to keep the async contract the real one needs.
  const verdict = ruleBasedEvaluator(input, probeResult);
  return { verdict, modelId: MODEL_ID };
}
