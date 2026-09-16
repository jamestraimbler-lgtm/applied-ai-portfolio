/**
 * /dashboard/listings/[id]/edit — edit an existing listing.
 *
 * Guards: signed in, is a seller, owns this listing. Otherwise redirect.
 */
import { redirect } from "next/navigation";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { db } from "@/server/db/client";
import { EditListingForm } from "./form";

export default async function EditListingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/sign-in");

  const seller = await db.sellerProfile.findFirst({
    where: { user: { authId: user.id }, deletedAt: null },
    select: { id: true },
  });
  if (!seller) redirect("/sell");

  // Ownership check: this listing must belong to this seller.
  const listing = await db.listing.findFirst({
    where: { id, sellerId: seller.id, deletedAt: null },
    select: { id: true },
  });
  if (!listing) redirect("/dashboard");

  return <EditListingForm listingId={id} />;
}
