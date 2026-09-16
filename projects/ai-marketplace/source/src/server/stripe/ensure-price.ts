/**
 * Lazily ensures a PricingPlan has a corresponding Stripe Product + Price.
 *
 * Called at checkout time so we never need a backfill migration. If the plan
 * already has a stripePriceId, this is a no-op.
 */
import type { PricingPlan } from "@prisma/client";
import { stripe } from "./client";
import { db } from "@/server/db/client";

export async function ensureStripePriceForPlan(
  plan: PricingPlan,
): Promise<string> {
  if (plan.stripePriceId) return plan.stripePriceId;

  // Create a Stripe Product for this plan.
  const product = await stripe.products.create({
    name: plan.name,
    metadata: { planId: plan.id, listingId: plan.listingId },
  });

  let price: { id: string };

  if (plan.model === "FLAT_RATE") {
    // Recurring flat-rate price.
    const interval = plan.interval === "YEAR" ? "year" : "month";
    price = await stripe.prices.create({
      product: product.id,
      unit_amount: plan.priceCents!,
      currency: plan.currency,
      recurring: { interval },
    });
  } else if (plan.model === "USAGE") {
    // Metered recurring price — reported via usage records.
    price = await stripe.prices.create({
      product: product.id,
      unit_amount: plan.unitPriceCents!,
      currency: plan.currency,
      recurring: { interval: "month", usage_type: "metered" },
    });
  } else {
    throw new Error(`Cannot create a Stripe price for model "${plan.model}"`);
  }

  // Persist so we don't recreate next time.
  await db.pricingPlan.update({
    where: { id: plan.id },
    data: { stripePriceId: price.id },
  });

  return price.id;
}
