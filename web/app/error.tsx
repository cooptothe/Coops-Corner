"use client";
import Link from "next/link";

export default function PageError({
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <main className="personal-workspace">
      <section className="trk-card account-card" role="alert">
        <h1>This page couldn’t load</h1>
        <p>Please try again. If the problem continues, contact support.</p>
        <div className="page-actions">
          <button type="button" className="button" onClick={retry}>
            Try again
          </button>
          <Link href="/positive_ev" className="button secondary">
            Back to workspace
          </Link>
          <a href="mailto:admin@coopscorner.tech">Contact support</a>
        </div>
      </section>
    </main>
  );
}
