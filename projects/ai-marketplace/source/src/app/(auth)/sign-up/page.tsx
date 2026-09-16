"use client";

import { useState } from "react";
import Link from "next/link";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";
import styles from "../auth.module.css";

export default function SignUpPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSignUp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError("Use a password of at least 8 characters.");
      return;
    }

    setBusy(true);
    const supabase = createSupabaseBrowserClient();
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      setError(error.message);
      setBusy(false);
      return;
    }

    // If email confirmation is on, there's no active session yet — tell them to
    // check their inbox. If it's off, Supabase returns a session immediately.
    if (data.session) {
      window.location.href = "/";
    } else {
      setDone(true);
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className={styles.authWrap}>
        <div className={`${styles.authCard} ${styles.successCard}`}>
          <div className={styles.check}>✓</div>
          <h1>Check your email</h1>
          <p className={styles.sub}>
            We sent a confirmation link to <strong>{email}</strong>. Click it to
            finish setting up your account, then sign in.
          </p>
          <Link className="btn btn-ghost" href="/sign-in" style={{ display: "inline-block", textDecoration: "none" }}>
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.authWrap}>
      <div className={styles.authCard}>
        <div className={styles.brand}>
          <span className={styles.bracket}>[</span>ai<span className={styles.bracket}>]</span> marketplace
        </div>

        <h1>Create your account</h1>
        <p className={styles.sub}>Browse, buy, and list AI agents.</p>

        {error && <div className="form-error">{error}</div>}

        <form onSubmit={handleSignUp}>
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
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <span className="form-note">At least 8 characters.</span>
          </div>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Creating account…" : "Create account"}
          </button>
        </form>

        <div className={styles.switchLine}>
          Already have an account? <Link href="/sign-in">Sign in</Link>
        </div>
      </div>
    </div>
  );
}
