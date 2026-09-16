/**
 * Slug helpers. Slugs are public URL identifiers, so they must be unique and
 * URL-safe. `ensureUniqueSlug` appends -2, -3, ... on collision.
 */
import type { PrismaClient } from "@prisma/client";

/** Turn an arbitrary name into a URL-safe base slug. */
export function slugify(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-") // non-alphanumerics -> hyphen
    .replace(/^-+|-+$/g, "") // trim leading/trailing hyphens
    .slice(0, 60);
}

/**
 * Return a slug guaranteed unique among Listings. On collision, append a
 * numeric suffix. Bounded loop so a pathological case can't spin forever.
 */
export async function ensureUniqueSlug(
  db: PrismaClient,
  base: string,
): Promise<string> {
  const safeBase = base || "listing";
  let candidate = safeBase;

  for (let i = 2; i < 1000; i++) {
    const existing = await db.listing.findUnique({
      where: { slug: candidate },
      select: { id: true },
    });
    if (!existing) return candidate;
    candidate = `${safeBase}-${i}`;
  }
  // Extremely unlikely; fall back to a time-based suffix.
  return `${safeBase}-${Date.now()}`;
}
