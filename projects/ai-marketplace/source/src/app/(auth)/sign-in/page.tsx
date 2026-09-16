"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";
import styles from "../auth.module.css";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);

    const supabase = createSupabaseBrowserClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });

    if (error) {
      setError(error.message);
      setBusy(false);
      return;
    }

    // Full reload so the server picks up the new session cookie everywhere.
    router.refresh();
    router.push("/");
  }

  return (
    <div className={styles.authWrap}>
      <div className={styles.authCard}>
        <div className={styles.brand}>
          <span className={styles.bracket}>[</span>ai<span className={styles.bracket}>]</span> marketplace
        </div>

        <h1>Sign in</h1>
        <p className={styles.sub}>Welcome back.</p>

        {error && <div className="form-error">{error}</div>}

        <form onSubmit={handleSignIn}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className={styles.switchLine}>
          New here? <Link href="/sign-up">Create an account</Link>
        </div>
      </div>
    </div>
  );
}
