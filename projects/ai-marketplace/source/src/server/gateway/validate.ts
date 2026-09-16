/**
 * Gateway access-key validation — portable, self-contained module.
 *
 * No Next.js imports. Takes a key + a Prisma-like db handle, returns a
 * discriminated result. This module can be extracted into a standalone
 * service later by moving it — nothing to untangle.
 *
 * SECURITY: the raw key is NEVER logged. Only the hash (for lookup) and
 * the subscription id (for audit) appear in any output.
 */
import { hashAccessKey } from "@/server/crypto/access-key";

const KEY_PREFIX = "mk_live_";

export type ValidationResult =
  | { ok: true; subscription: { id: string; listingId: string; buyerId: string } }
  | { ok: false; reason: "malformed" | "not_found" | "inactive" };

/**
 * Validate a presented access key against ACTIVE subscription state.
 *
 * @param key  The raw key from the client (e.g. "mk_live_abc123...")
 * @param db   A Prisma client (or any object with subscription.findFirst)
 */
export async function validateAccessKey(
  key: string,
  db: {
    subscription: {
      findFirst: (args: {
        where: { accessKeyHash: string };
        select: { id: true; listingId: true; buyerId: true; status: true };
      }) => Promise<{
        id: string;
        listingId: string;
        buyerId: string;
        status: string;
      } | null>;
    };
  },
): Promise<ValidationResult> {
  // Shape check: must start with the expected prefix and be the right length.
  if (!key.startsWith(KEY_PREFIX) || key.length !== KEY_PREFIX.length + 32) {
    return { ok: false, reason: "malformed" };
  }

  const keyHash = hashAccessKey(key);

  const sub = await db.subscription.findFirst({
    where: { accessKeyHash: keyHash },
    select: { id: true, listingId: true, buyerId: true, status: true },
  });

  if (!sub) {
    return { ok: false, reason: "not_found" };
  }

  if (sub.status !== "ACTIVE") {
    return { ok: false, reason: "inactive" };
  }

  return {
    ok: true,
    subscription: { id: sub.id, listingId: sub.listingId, buyerId: sub.buyerId },
  };
}
