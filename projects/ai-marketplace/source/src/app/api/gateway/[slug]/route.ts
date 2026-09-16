/**
 * Gateway route — thin wrapper around the portable validation module.
 *
 * Stage 1: validates the access key and confirms authorization. Returns JSON
 * indicating whether access would be granted. Stage 2 will forward to the
 * real MCP server through this same route.
 *
 * Auth is via the access key (Bearer token or x-api-key header), NOT the
 * Supabase session — this route is excluded from auth middleware.
 */
import { NextResponse, type NextRequest } from "next/server";
import { db } from "@/server/db/client";
import { validateAccessKey } from "@/server/gateway/validate";

function extractKey(request: NextRequest): string | null {
  // Try Authorization: Bearer <key>
  const auth = request.headers.get("authorization");
  if (auth?.startsWith("Bearer ")) {
    return auth.slice(7).trim();
  }
  // Fallback: x-api-key header
  const xApiKey = request.headers.get("x-api-key");
  if (xApiKey) {
    return xApiKey.trim();
  }
  return null;
}

async function handleRequest(
  request: NextRequest,
  params: Promise<{ slug: string }>,
) {
  const { slug } = await params;
  const key = extractKey(request);

  if (!key) {
    return NextResponse.json(
      { authorized: false, reason: "missing_key" },
      { status: 401 },
    );
  }

  const result = await validateAccessKey(key, db);

  if (!result.ok) {
    const status = result.reason === "inactive" ? 403 : 401;
    return NextResponse.json(
      { authorized: false, reason: result.reason },
      { status },
    );
  }

  // Verify the key matches the requested listing (no cross-agent use).
  const listing = await db.listing.findFirst({
    where: { slug, deletedAt: null },
    select: { id: true },
  });

  if (!listing) {
    return NextResponse.json(
      { authorized: false, reason: "listing_not_found" },
      { status: 404 },
    );
  }

  if (result.subscription.listingId !== listing.id) {
    return NextResponse.json(
      { authorized: false, reason: "wrong_listing" },
      { status: 403 },
    );
  }

  return NextResponse.json(
    {
      authorized: true,
      listing: slug,
      subscriptionId: result.subscription.id,
    },
    { status: 200 },
  );
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  return handleRequest(request, params);
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  return handleRequest(request, params);
}
