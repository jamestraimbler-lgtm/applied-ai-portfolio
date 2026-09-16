/**
 * /dashboard/listings/new — create an additional listing (for existing sellers).
 *
 * Guards: signed in, is a seller. Otherwise redirect.
 */
import { redirect } from "next/navigation";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { db } from "@/server/db/client";
import { NewListingForm } from "./form";

export default async function NewListingPage() {
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

  return <NewListingForm />;
}
