/**
 * /sell/onboarding — the page wrapper for the onboarding flow.
 *
 * Server-side guards before rendering the (client) flow:
 *  - Not signed in -> send to sign-in.
 *  - Already a seller -> send to the dashboard (no re-onboarding).
 */
import { redirect } from "next/navigation";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { db } from "@/server/db/client";
import { OnboardingFlow } from "./flow";

export default async function OnboardingPage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/sign-in");

  const existingSeller = await db.sellerProfile.findFirst({
    where: { user: { authId: user.id }, deletedAt: null },
    select: { id: true },
  });
  if (existingSeller) redirect("/dashboard");

  return <OnboardingFlow />;
}
