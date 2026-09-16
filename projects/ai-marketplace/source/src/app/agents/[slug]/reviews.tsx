"use client";

/**
 * Reviews section — review list + write/edit form. Client island on the agent
 * detail page. Verified subscribers can leave star-only reviews; others must
 * include written text (enforced server-side, hinted in the UI).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/trpc";
import styles from "@/app/_components/storefront.module.css";

function Stars({ rating, onSelect }: { rating: number; onSelect?: (n: number) => void }) {
  return (
    <span className={styles.stars}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={`${styles.star} ${n <= rating ? styles.starFilled : ""}`}
          onClick={onSelect ? () => onSelect(n) : undefined}
          style={onSelect ? { cursor: "pointer" } : undefined}
          role={onSelect ? "button" : undefined}
          aria-label={onSelect ? `Rate ${n} star${n > 1 ? "s" : ""}` : undefined}
        >
          ★
        </span>
      ))}
    </span>
  );
}

function ReviewForm({ listingId }: { listingId: string }) {
  const router = useRouter();
  const utils = api.useUtils();

  // Check if user has a subscription (to determine verified status for hint).
  const { data: subStatus } = api.subscription.statusForListing.useQuery(
    { listingId },
    { retry: false },
  );
  const isSubscriber = subStatus?.active;

  // Load existing review for pre-fill.
  const { data: existing } = api.review.myReview.useQuery(
    { id: listingId },
    { retry: false },
  );

  const [rating, setRating] = useState(0);
  const [body, setBody] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Pre-fill from existing review once loaded.
  if (existing && !initialized) {
    setRating(existing.rating);
    setBody(existing.body ?? "");
    setInitialized(true);
  }

  const upsert = api.review.upsert.useMutation({
    onSuccess: () => {
      setMsg({ kind: "ok", text: existing ? "Review updated." : "Review submitted." });
      utils.review.forListing.invalidate({ id: listingId });
      utils.review.myReview.invalidate({ id: listingId });
      router.refresh();
    },
    onError: (e) => {
      if (e.data?.code === "UNAUTHORIZED") {
        router.push("/sign-in");
        return;
      }
      setMsg({ kind: "err", text: e.message });
    },
  });

  return (
    <div className={styles.reviewForm}>
      <div className={styles.reviewFormTitle}>
        {existing ? "Edit your review" : "Write a review"}
      </div>

      <div style={{ margin: "0.4rem 0 0.6rem" }}>
        <Stars rating={rating} onSelect={setRating} />
        {rating === 0 && <span style={{ fontSize: "0.78rem", color: "var(--muted)", marginLeft: "0.5rem" }}>Select a rating</span>}
      </div>

      <textarea
        className={styles.reviewTextarea}
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder={isSubscriber ? "Share your experience (optional for subscribers)..." : "Share your experience (required, at least 20 characters)..."}
      />
      {!isSubscriber && (
        <p style={{ fontSize: "0.72rem", color: "var(--muted)", margin: "0.25rem 0 0" }}>
          Written feedback is required for non-subscribers (min 20 characters).
        </p>
      )}

      <button
        className="btn"
        style={{ marginTop: "0.5rem", padding: "0.5rem 1rem" }}
        disabled={upsert.isPending || rating === 0}
        onClick={() => {
          setMsg(null);
          upsert.mutate({ listingId, rating, body: body.trim() || undefined });
        }}
      >
        {upsert.isPending ? "Submitting..." : existing ? "Update review" : "Submit review"}
      </button>

      {msg && (
        <div
          style={{
            marginTop: "0.5rem",
            padding: "0.5rem 0.65rem",
            borderRadius: "var(--radius)",
            fontSize: "0.8rem",
            background: msg.kind === "ok" ? "var(--accent-tint)" : "var(--danger-tint)",
            color: msg.kind === "ok" ? "var(--accent)" : "var(--danger)",
          }}
        >
          {msg.text}
        </div>
      )}
    </div>
  );
}

export function ReviewsSection({ listingId }: { listingId: string }) {
  const { data: reviews, isLoading } = api.review.forListing.useQuery({ id: listingId });

  return (
    <div>
      <div className={styles.sectionLabel}>Reviews</div>

      <ReviewForm listingId={listingId} />

      {isLoading && <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: "1rem" }}>Loading reviews...</p>}

      {reviews && reviews.length > 0 && (
        <div className={styles.reviewList}>
          {reviews.map((r) => (
            <div key={r.id} className={styles.reviewItem}>
              <div className={styles.reviewHead}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                  <span className={styles.reviewAuthor}>
                    {r.buyer?.displayName ?? "Anonymous"}
                  </span>
                  {r.isVerified && (
                    <span className={styles.verifiedBadge}>Verified</span>
                  )}
                </div>
                <Stars rating={r.rating} />
              </div>
              {r.body && <div className={styles.reviewBody}>{r.body}</div>}
              <div className={styles.reviewDate}>
                {new Date(r.createdAt).toLocaleDateString("en-US", {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {reviews && reviews.length === 0 && (
        <p style={{ color: "var(--muted)", fontSize: "0.88rem", marginTop: "0.75rem" }}>
          No reviews yet. Be the first to share your experience.
        </p>
      )}
    </div>
  );
}
