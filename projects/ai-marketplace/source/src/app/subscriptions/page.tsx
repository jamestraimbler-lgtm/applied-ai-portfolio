/**
 * /subscriptions — the buyer's subscriptions. What they've subscribed to, with
 * a cancel action. Guard: must be signed in.
 */
import { redirect } from "next/navigation";
import Link from "next/link";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { signOut } from "../(auth)/actions";
import { SubscriptionList } from "./list";
import styles from "@/app/_components/storefront.module.css";

export default async function SubscriptionsPage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in");

  return (
    <main className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/" className={styles.brand}>
          <span className={styles.bk}>[</span>ai<span className={styles.bk}>]</span> marketplace
        </Link>
        <div className={styles.navRight}>
          <Link href="/">Browse all</Link>
          <form action={signOut}>
            <button className="btn btn-ghost" type="submit" style={{ padding: "0.4rem 0.8rem" }}>Sign out</button>
          </form>
        </div>
      </nav>

      <section style={{ padding: "2.5rem 0 1.5rem" }}>
        <h1 style={{ fontSize: "1.7rem", fontWeight: 650, letterSpacing: "-0.02em", margin: "0 0 0.3rem" }}>
          Your subscriptions
        </h1>
        <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.92rem" }}>
          The agents you’ve subscribed to.
        </p>
      </section>

      <SubscriptionList />
    </main>
  );
}
