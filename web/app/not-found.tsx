import Link from "next/link";
export default function NotFound() {
  return (
    <main className="personal-workspace">
      <section className="trk-card account-card">
        <p className="eyebrow">PAGE NOT FOUND</p>
        <h1>Let’s get you back to The Corner</h1>
        <p>This link may have changed. Choose where you’d like to go.</p>
        <div className="page-actions">
          <Link className="button" href="/positive_ev">
            Open workspace
          </Link>
          <Link className="button secondary" href="/lab">
            Explore The Lab
          </Link>
        </div>
      </section>
    </main>
  );
}
