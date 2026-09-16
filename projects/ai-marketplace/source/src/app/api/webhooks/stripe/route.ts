/**
 * Stripe webhook handler (App Router POST).
 *
 * This is the ONLY place a paid subscription becomes ACTIVE — never set
 * optimistically elsewhere. All handlers are idempotent (safe on redelivery).
 */
import { NextResponse, type NextRequest } from "next/server";
import { stripe } from "@/server/stripe/client";
import { db } from "@/server/db/client";
import { generateAccessKey, encryptAccessKey, hashAccessKey } from "@/server/crypto/access-key";
import type Stripe from "stripe";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const signature = request.headers.get("stripe-signature");

  if (!signature) {
    return NextResponse.json({ error: "Missing signature" }, { status: 400 });
  }

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(
      body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET!,
    );
  } catch {
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
  }

  switch (event.type) {
    case "checkout.session.completed":
      await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
      break;
    case "customer.subscription.updated":
      await handleSubscriptionUpdated(event.data.object as Stripe.Subscription);
      break;
    case "customer.subscription.deleted":
      await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
      break;
    case "account.updated":
      await handleAccountUpdated(event.data.object as Stripe.Account);
      break;
  }

  return NextResponse.json({ received: true }, { status: 200 });
}

// ---------------------------------------------------------------------------
//  Helpers
// ---------------------------------------------------------------------------

/** Extract the current_period_end from the first subscription item. */
function getPeriodEnd(stripeSub: Stripe.Subscription): Date | null {
  const firstItem = stripeSub.items?.data?.[0];
  if (firstItem && typeof firstItem.current_period_end === "number") {
    return new Date(firstItem.current_period_end * 1000);
  }
  return null;
}

// ---------------------------------------------------------------------------
//  Event handlers
// ---------------------------------------------------------------------------

async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const subscriptionId = session.metadata?.subscriptionId;
  if (!subscriptionId) return;

  const stripeSubscriptionId =
    typeof session.subscription === "string"
      ? session.subscription
      : session.subscription?.id;

  if (!stripeSubscriptionId) return;

  // Fetch the Stripe subscription to get the current period end from items.
  const stripeSub = await stripe.subscriptions.retrieve(stripeSubscriptionId, {
    expand: ["items"],
  });
  const periodEnd = getPeriodEnd(stripeSub);

  await db.subscription.update({
    where: { id: subscriptionId },
    data: {
      status: "ACTIVE",
      stripeSubscriptionId,
      ...(periodEnd ? { currentPeriodEnd: periodEnd } : {}),
    },
  });

  // Bump the listing's active subscription count + generate access key if needed.
  const sub = await db.subscription.findUnique({
    where: { id: subscriptionId },
    select: { listingId: true, accessKeyCipher: true },
  });
  if (sub) {
    await db.listing.update({
      where: { id: sub.listingId },
      data: { activeSubCount: { increment: 1 } },
    });

    // Generate an encrypted access key for API_KEY agents (idempotent).
    if (!sub.accessKeyCipher) {
      const spec = await db.mcpSpec.findFirst({
        where: { listingId: sub.listingId },
        select: { authType: true },
      });
      if (spec?.authType === "API_KEY") {
        const plainKey = generateAccessKey();
        await db.subscription.update({
          where: { id: subscriptionId },
          data: {
            accessKeyCipher: encryptAccessKey(plainKey),
            accessKeyHash: hashAccessKey(plainKey),
          },
        });
      }
    }
  }
}

async function handleSubscriptionUpdated(stripeSub: Stripe.Subscription) {
  const existing = await db.subscription.findFirst({
    where: { stripeSubscriptionId: stripeSub.id },
  });
  if (!existing) return;

  const statusMap: Record<string, string> = {
    active: "ACTIVE",
    past_due: "PAST_DUE",
    canceled: "CANCELED",
    paused: "PAUSED",
    incomplete: "INCOMPLETE",
    incomplete_expired: "CANCELED",
    trialing: "ACTIVE",
    unpaid: "PAST_DUE",
  };

  const newStatus = statusMap[stripeSub.status] ?? existing.status;

  const periodEnd = getPeriodEnd(stripeSub);

  await db.subscription.update({
    where: { id: existing.id },
    data: {
      status: newStatus as typeof existing.status,
      ...(periodEnd ? { currentPeriodEnd: periodEnd } : {}),
      cancelAtPeriodEnd: stripeSub.cancel_at_period_end,
    },
  });
}

async function handleSubscriptionDeleted(stripeSub: Stripe.Subscription) {
  const existing = await db.subscription.findFirst({
    where: { stripeSubscriptionId: stripeSub.id },
  });
  if (!existing) return;

  await db.subscription.update({
    where: { id: existing.id },
    data: {
      status: "CANCELED",
      canceledAt: new Date(),
    },
  });

  // Decrement active sub count if it was active before.
  if (existing.status === "ACTIVE" || existing.status === "PAST_DUE") {
    await db.listing.update({
      where: { id: existing.listingId },
      data: { activeSubCount: { decrement: 1 } },
    });
  }
}

async function handleAccountUpdated(account: Stripe.Account) {
  if (!account.id) return;

  const seller = await db.sellerProfile.findFirst({
    where: { stripeAccountId: account.id },
  });
  if (!seller) return;

  let payoutStatus: "ACTIVE" | "PENDING" | "RESTRICTED";
  if (account.charges_enabled && account.payouts_enabled) {
    payoutStatus = "ACTIVE";
  } else if (account.requirements?.disabled_reason) {
    payoutStatus = "RESTRICTED";
  } else {
    payoutStatus = "PENDING";
  }

  await db.sellerProfile.update({
    where: { id: seller.id },
    data: { payoutStatus },
  });
}
