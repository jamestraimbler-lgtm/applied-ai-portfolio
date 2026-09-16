/**
 * Zod schemas — the single source of validation truth.
 *
 * These are imported by BOTH the client (form validation) and the server
 * (tRPC input validation), so a field's rules are defined exactly once. If you
 * change a constraint here, every consumer gets it. This is half of what makes
 * the stack "solid" — you can't drift the client and server apart.
 *
 * Note on money: all prices are integer minor units (cents). See DATA_MODEL.md.
 */
import { z } from "zod";

// ---------------------------------------------------------------------------
//  Primitives / reusable pieces
// ---------------------------------------------------------------------------

/** A URL-safe slug: lowercase letters, numbers, hyphens. */
export const slugSchema = z
  .string()
  .min(3, "Must be at least 3 characters")
  .max(60, "Must be 60 characters or fewer")
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Use lowercase letters, numbers, and hyphens only");

/** A seller's public handle — same rules as a slug. */
export const handleSchema = slugSchema;

/** Money in integer cents. Rejects floats and negatives. */
export const centsSchema = z
  .number()
  .int("Amount must be in whole cents (no fractions)")
  .nonnegative("Amount cannot be negative");

/** ISO 4217-ish currency code. Kept simple; expand the enum as you add support. */
export const currencySchema = z.enum(["usd", "eur", "gbp"]).default("usd");

// ---------------------------------------------------------------------------
//  Enums — mirror the Prisma enums so client + server agree on the value set.
//  (We redeclare rather than import from @prisma/client so these are usable in
//  the browser bundle without dragging Prisma client-side.)
// ---------------------------------------------------------------------------

export const listingStatusSchema = z.enum([
  "DRAFT",
  "IN_REVIEW",
  "PUBLISHED",
  "REJECTED",
  "SUSPENDED",
  "ARCHIVED",
]);

export const sellerStatusSchema = z.enum(["ONBOARDING", "ACTIVE", "SUSPENDED"]);

export const reviewVerdictSchema = z.enum([
  "PENDING",
  "APPROVED",
  "REJECTED",
  "ESCALATED",
]);

export const reviewedBySchema = z.enum(["AGENT", "HUMAN"]);

export const mcpTransportSchema = z.enum(["STDIO", "SSE", "STREAMABLE_HTTP"]);
export const mcpAuthTypeSchema = z.enum(["NONE", "API_KEY", "OAUTH"]);
export const pricingModelSchema = z.enum(["FREE", "FLAT_RATE", "USAGE"]);
export const billingIntervalSchema = z.enum(["MONTH", "YEAR"]);

// ---------------------------------------------------------------------------
//  MCP capabilities — the shape of McpSpec.capabilities (stored as JSON).
//  Validating this BEFORE it lands in the DB is rule #11 from the data model:
//  the JSON column is only as trustworthy as the validation in front of it.
// ---------------------------------------------------------------------------

export const mcpToolSchema = z.object({
  name: z.string().min(1).max(100),
  description: z.string().max(500).optional(),
});

export const mcpCapabilitiesSchema = z.object({
  tools: z.array(mcpToolSchema).max(200).default([]),
  // Room to grow: resources, prompts, etc. — add as MCP evolves.
  resources: z
    .array(z.object({ name: z.string().min(1), uri: z.string().optional() }))
    .max(200)
    .optional(),
});
export type McpCapabilities = z.infer<typeof mcpCapabilitiesSchema>;

// ---------------------------------------------------------------------------
//  Seller profile
// ---------------------------------------------------------------------------

export const createSellerProfileSchema = z.object({
  handle: handleSchema,
  displayName: z.string().min(2).max(80),
  bio: z.string().max(1000).optional(),
  websiteUrl: z.string().url().max(300).optional(),
  // Declared during onboarding; primes the Stripe step and informs review.
  intendedPricingModel: pricingModelSchema.optional(),
});

export const updateSellerProfileSchema = createSellerProfileSchema
  .partial()
  // handle changes are sensitive (they're in URLs) — disallow here; do it via a
  // dedicated flow if ever needed.
  .omit({ handle: true });

// The shape submitted by the onboarding flow's final step. Same fields as
// create, but intendedPricingModel is required here because onboarding asks for
// it explicitly before completion.
export const completeOnboardingSchema = z.object({
  handle: handleSchema,
  displayName: z.string().min(2).max(80),
  bio: z.string().max(1000).optional(),
  websiteUrl: z.string().url().max(300).optional(),
  intendedPricingModel: pricingModelSchema,
});

// ---------------------------------------------------------------------------
//  Listing review (the approval agent's structured verdict)
// ---------------------------------------------------------------------------

export const riskFlagSchema = z.object({
  code: z.string().min(1).max(60),
  detail: z.string().max(500),
  severity: z.enum(["low", "medium", "high"]),
});

/** The structured object the approval agent must return. */
export const agentVerdictSchema = z.object({
  // The agent decides among these three; PENDING is never produced by the agent.
  verdict: z.enum(["APPROVED", "REJECTED", "ESCALATED"]),
  reasoning: z.string().min(1).max(2000),
  riskFlags: z.array(riskFlagSchema).max(50).default([]),
  riskScore: z.number().int().min(0).max(100),
});
export type AgentVerdict = z.infer<typeof agentVerdictSchema>;

// ---------------------------------------------------------------------------
//  Capability probe result — returned by the MCP endpoint prober.
// ---------------------------------------------------------------------------

export const probeResultSchema = z.object({
  reachable: z.boolean(),
  probedTools: z.array(z.string()).nullable(),
  mismatch: z
    .object({
      undeclared: z.array(z.string()),
      missing: z.array(z.string()),
    })
    .nullable(),
  error: z.string().nullable(),
  sensitiveUndeclared: z.array(z.string()),
});
export type ProbeResult = z.infer<typeof probeResultSchema>;

// ---------------------------------------------------------------------------
//  MCP spec (the technical contract attached to a listing)
// ---------------------------------------------------------------------------

export const mcpSpecSchema = z
  .object({
    transport: mcpTransportSchema,
    endpointUrl: z.string().url().max(500).optional(),
    authType: mcpAuthTypeSchema,
    capabilities: mcpCapabilitiesSchema,
    protocolVersion: z.string().max(20).optional(),
  })
  // A remote transport requires an endpoint; stdio must not have one.
  .refine(
    (s) => (s.transport === "STDIO" ? !s.endpointUrl : !!s.endpointUrl),
    {
      message: "Remote transports require an endpoint URL; stdio must not have one",
      path: ["endpointUrl"],
    },
  );

// ---------------------------------------------------------------------------
//  Pricing plan
// ---------------------------------------------------------------------------

export const pricingPlanSchema = z
  .object({
    name: z.string().min(1).max(40),
    model: pricingModelSchema,
    priceCents: centsSchema.optional(),
    currency: currencySchema,
    interval: billingIntervalSchema.optional(),
    unitPriceCents: centsSchema.optional(),
    unitLabel: z.string().max(40).optional(),
  })
  // Cross-field rules so a plan can't be internally contradictory:
  .superRefine((plan, ctx) => {
    if (plan.model === "FLAT_RATE") {
      if (plan.priceCents == null)
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["priceCents"], message: "Flat-rate plans need a price" });
      if (plan.interval == null)
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["interval"], message: "Flat-rate plans need a billing interval" });
    }
    if (plan.model === "USAGE") {
      if (plan.unitPriceCents == null)
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["unitPriceCents"], message: "Usage plans need a per-unit price" });
      if (!plan.unitLabel)
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["unitLabel"], message: "Usage plans need a unit label (e.g. 'per call')" });
    }
    if (plan.model === "FREE" && (plan.priceCents || plan.unitPriceCents)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["priceCents"], message: "Free plans can't have a price" });
    }
  });

// ---------------------------------------------------------------------------
//  Listing — create / update / publish
// ---------------------------------------------------------------------------

export const createListingSchema = z.object({
  name: z.string().min(3).max(80),
  tagline: z.string().min(10, "Give buyers a real one-liner").max(140),
  description: z.string().min(30).max(10_000),
  iconUrl: z.string().url().max(500).optional(),
  categoryIds: z.array(z.string().cuid()).max(5).default([]),
  // A listing is created with its spec and at least one plan, so it's never in
  // a half-built state.
  mcpSpec: mcpSpecSchema,
  plans: z.array(pricingPlanSchema).min(1, "Add at least one pricing plan").max(5),
});

export const updateListingSchema = z.object({
  id: z.string().cuid(),
  name: z.string().min(3).max(80).optional(),
  tagline: z.string().min(10).max(140).optional(),
  description: z.string().min(30).max(10_000).optional(),
  iconUrl: z.string().url().max(500).optional(),
  categoryIds: z.array(z.string().cuid()).max(5).optional(),
  mcpSpec: mcpSpecSchema.optional(),
  plans: z.array(pricingPlanSchema).min(1).max(5).optional(),
});

export const listingIdSchema = z.object({ id: z.string().cuid() });
export const listingSlugSchema = z.object({ slug: slugSchema });

// ---------------------------------------------------------------------------
//  Catalog browsing — pagination + filters
// ---------------------------------------------------------------------------

export const catalogQuerySchema = z.object({
  search: z.string().max(100).optional(),
  categorySlug: slugSchema.optional(),
  price: z.enum(["all", "free", "paid"]).default("all"),
  sort: z.enum(["top_rated", "newest", "most_popular"]).default("top_rated"),
  // Cursor pagination (more scalable than offset for a growing catalog).
  cursor: z.string().cuid().optional(),
  limit: z.number().int().min(1).max(50).default(20),
});

// ---------------------------------------------------------------------------
//  Subscriptions
// ---------------------------------------------------------------------------

export const createSubscriptionSchema = z.object({
  listingId: z.string().cuid(),
  planId: z.string().cuid(),
});

export const subscriptionIdSchema = z.object({ id: z.string().cuid() });

// ---------------------------------------------------------------------------
//  Reviews
// ---------------------------------------------------------------------------

export const createReviewSchema = z.object({
  listingId: z.string().cuid(),
  rating: z.number().int().min(1, "Rating is 1–5").max(5, "Rating is 1–5"),
  body: z.string().max(2000).optional(),
});

// ---------------------------------------------------------------------------
//  Inferred types — import these instead of redeclaring shapes anywhere.
// ---------------------------------------------------------------------------

export type CreateListingInput = z.infer<typeof createListingSchema>;
export type UpdateListingInput = z.infer<typeof updateListingSchema>;
export type CatalogQuery = z.infer<typeof catalogQuerySchema>;
export type PricingPlanInput = z.infer<typeof pricingPlanSchema>;
export type CreateSubscriptionInput = z.infer<typeof createSubscriptionSchema>;
export type CreateReviewInput = z.infer<typeof createReviewSchema>;
export type CreateSellerProfileInput = z.infer<typeof createSellerProfileSchema>;

// ---------------------------------------------------------------------------
//  Onboarding-with-listing (defined last: depends on mcpSpecSchema +
//  pricingPlanSchema + slugSchema declared above).
// ---------------------------------------------------------------------------

// The full onboarding payload: storefront profile + the seller's first agent
// listing (spec + pricing), submitted together and created in one transaction.
export const onboardingWithListingSchema = z.object({
  profile: z.object({
    handle: handleSchema,
    displayName: z.string().min(2).max(80),
    bio: z.string().max(1000).optional(),
    websiteUrl: z.string().url().max(300).optional(),
  }),
  listing: z.object({
    name: z.string().min(3).max(80),
    tagline: z.string().min(10, "Give buyers a real one-liner").max(140),
    description: z.string().min(30).max(10_000),
    iconUrl: z.string().url().max(500).optional(),
    categorySlug: slugSchema.optional(),
    mcpSpec: mcpSpecSchema,
    plans: z.array(pricingPlanSchema).min(1, "Add at least one pricing plan").max(5),
  }),
});
export type OnboardingWithListingInput = z.infer<typeof onboardingWithListingSchema>;
