/**
 * Display helpers for listings — formatting money and summarizing a spec.
 * Money is stored as integer cents; we convert to a human string only here, at
 * the display edge.
 */

interface PlanLike {
  model: "FREE" | "FLAT_RATE" | "USAGE";
  priceCents?: number | null;
  currency?: string;
  interval?: "MONTH" | "YEAR" | null;
  unitPriceCents?: number | null;
  unitLabel?: string | null;
}

const CURRENCY_SYMBOL: Record<string, string> = { usd: "$", eur: "€", gbp: "£" };

function money(cents: number, currency = "usd") {
  const sym = CURRENCY_SYMBOL[currency] ?? "$";
  return `${sym}${(cents / 100).toFixed(2).replace(/\.00$/, "")}`;
}

/**
 * Pick the headline plan to show on a card / rail: prefer the cheapest paid
 * plan's "from" price, else Free. Returns a short label + optional sub-label.
 */
export function priceLabel(plans: PlanLike[]): { main: string; sub?: string } {
  if (!plans || plans.length === 0) return { main: "—" };

  const hasFree = plans.some((p) => p.model === "FREE");
  const paid = plans.filter((p) => p.model !== "FREE");

  if (paid.length === 0) return { main: "Free" };

  // Cheapest paid plan by its headline number.
  const cheapest = paid
    .map((p) => ({
      p,
      n: p.model === "FLAT_RATE" ? (p.priceCents ?? 0) : (p.unitPriceCents ?? 0),
    }))
    .sort((a, b) => a.n - b.n)[0]!.p;

  if (cheapest.model === "FLAT_RATE") {
    const per = cheapest.interval === "YEAR" ? "/yr" : "/mo";
    return {
      main: `${hasFree ? "From " : ""}${money(cheapest.priceCents ?? 0, cheapest.currency)}`,
      sub: per,
    };
  }
  // USAGE
  return {
    main: `${money(cheapest.unitPriceCents ?? 0, cheapest.currency)}`,
    sub: cheapest.unitLabel ?? "per use",
  };
}

/** Count the tools a spec's capabilities JSON advertises. */
export function toolCount(capabilities: unknown): number {
  if (
    capabilities &&
    typeof capabilities === "object" &&
    "tools" in capabilities &&
    Array.isArray((capabilities as { tools: unknown[] }).tools)
  ) {
    return (capabilities as { tools: unknown[] }).tools.length;
  }
  return 0;
}

/** Extract the tool list (name + optional description) for the detail page. */
export function extractTools(capabilities: unknown): Array<{ name: string; description?: string }> {
  if (
    capabilities &&
    typeof capabilities === "object" &&
    "tools" in capabilities &&
    Array.isArray((capabilities as { tools: unknown[] }).tools)
  ) {
    return (capabilities as { tools: Array<{ name: string; description?: string }> }).tools;
  }
  return [];
}

/** Friendly transport label. */
export function transportLabel(t?: string | null): string {
  if (t === "STREAMABLE_HTTP") return "HTTP";
  if (t === "SSE") return "SSE";
  if (t === "STDIO") return "stdio";
  return "—";
}
