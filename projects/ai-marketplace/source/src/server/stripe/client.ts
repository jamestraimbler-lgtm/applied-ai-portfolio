/**
 * Stripe client — single configured instance for the whole server.
 *
 * Reads STRIPE_SECRET_KEY from the environment. The apiVersion is pinned so
 * webhook payloads and SDK types stay in sync across deploys.
 */
import Stripe from "stripe";

if (!process.env.STRIPE_SECRET_KEY) {
  throw new Error("Missing STRIPE_SECRET_KEY environment variable");
}

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY, {
  apiVersion: "2026-05-27.dahlia",
  typescript: true,
});

/** Platform's cut on every transaction, in percent. */
export const PLATFORM_FEE_PERCENT = 10;
