"use client";
import { useEffect, useState, useRef, type FormEvent } from "react";
import {
  invitationToken,
  invitationRequest,
  type InvitationOffer,
} from "../lib/invitation-api";
import { useAuth } from "./auth-provider";
const lessons = [
  [
    "Positive EV · Shop the price",
    "EV compares an estimated fair chance with the offered payout, after modeled fees. EV = probability × decimal odds − 1. At +150 (2.50 decimal), a hypothetical 45% chance gives 12.5% EV. That does not mean a 12.5% chance to win or a guaranteed profit. Compare the exact market, line, settlement rules and timestamp. Fair-odds filters use the estimate, not the offered price.",
  ],
  [
    "Player props · Know the assumptions",
    "Match the player, stat, line and game. Two-sided reference prices can be de-vigged to remove the bookmaker margin; a simple example normalizes the two implied probabilities. One-sided estimates need additional assumptions and can be much less certain. Missing data is not proof of value. Reference policy is fixed by the app; changing a display filter does not change the probability.",
  ],
  [
    "The Lab · Research before you bet",
    "Browse games and available props, then inspect recent game logs, hit rates and matchup context. An 8/10 historical hit rate is not an 80% forecast. Check minutes, role, injuries, opponent and sample size. Avoid cherry-picking only the window that looks best. Free-source data may be incomplete or delayed.",
  ],
  [
    "Arbitrage · Check both sides",
    "Compare a complete set of mutually exclusive outcomes with matching settlement rules. The apparent return assumes all legs are accepted at the displayed prices and stakes. Limits, fees, liquidity, movement and different void rules can remove it. Confirm each bet yourself; the app does not execute wagers.",
  ],
  [
    "Middles · Understand the miss",
    "Two different lines create a range where both bets may win. Outside it, one side can lose more than the other wins. Review every payoff, including pushes and voids. A wider window alone does not establish a positive expected return.",
  ],
  [
    "Promo converter · Read the offer",
    "Enter the actual bonus amount, qualifying odds and restrictions. Bonus stakes may not be returned; caps, expiry and settlement rules vary. A calculator result is conditional on those inputs and on the hedge being accepted.",
  ],
  [
    "Parlays & same-game parlays · Respect correlation",
    "Every leg must win unless the sportsbook applies different rules. Same-game outcomes can be correlated, so multiplying individual win probabilities is not a reliable joint estimate. Use the sportsbook’s accepted combined American odds when recording your bet. A larger payout usually means a lower chance of collecting.",
  ],
  [
    "Tracker & CLV · Keep honest records",
    "Record the actual accepted odds, stake and time, including losses. CLV compares your entry with an available closing reference for the same selection. Missing closing data means unavailable CLV. Positive CLV is a useful diagnostic, not a guarantee of profit.",
  ],
  [
    "Schedule & freshness · Check the clock",
    "Confirm the matchup, start time and stored quote timestamp. Stored odds are not a live promise. An empty feed can simply mean no qualifying opportunities or insufficient data; it is not a reason to place a weaker bet.",
  ],
];
export default function InvitationPage() {
  const { status } = useAuth();
  const [token, setToken] = useState("");
  const [offer, setOffer] = useState<InvitationOffer | null>(null);
  const [opened, setOpened] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [eligible, setEligible] = useState(false);
  const [agree, setAgree] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [copied, setCopied] = useState(false);
  const [receipt, setReceipt] = useState("");
  const requestGeneration = useRef(0);
  useEffect(() => {
    function readCode() {
      requestGeneration.current++;
      setToken(invitationToken(window.location.hash));
      setOffer(null);
      setOpened(false);
      setAccepted(false);
      setEligible(false);
      setAgree(false);
      setError("");
      setBusy(false);
      setReceipt("");
      setCopied(false);
    }
    readCode();
    window.addEventListener("hashchange", readCode);
    return () => {
      requestGeneration.current++;
      window.removeEventListener("hashchange", readCode);
    };
  }, []);
  async function open() {
    const generation = ++requestGeneration.current;
    setBusy(true);
    setError("");
    try {
      if (!token)
        throw new Error(
          "This link is missing its private code. Ask your host for the complete invitation link.",
        );
      const current = await invitationRequest<InvitationOffer>("preview", {
        token,
      });
      if (generation !== requestGeneration.current) return;
      setOffer(current);
      setAccepted(current.claimed);
      setOpened(true);
    } catch (e) {
      if (generation === requestGeneration.current)
        setError((e as Error).message);
    } finally {
      if (generation === requestGeneration.current) setBusy(false);
    }
  }
  async function accept() {
    setBusy(true);
    setError("");
    try {
      await invitationRequest("accept", {
        token,
        version: offer!.version,
        terms_version: offer!.terms_version,
        eligible,
        agree,
      });
      setAccepted(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function feedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setReceipt("");
    try {
      const result = await invitationRequest<{ reference: number }>(
        "feedback",
        {
          token,
          category: data.get("category"),
          title: data.get("title"),
          message: data.get("message"),
        },
      );
      setReceipt(
        `Received. Your reference is #${result.reference}. Thank you for helping build The Corner.`,
      );
      form.reset();
    } catch (e) {
      setReceipt((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="family-invite">
      <div className="family-wrap">
        <header className="family-brand">
          <img
            src="/assets/corner-logo.png"
            width="56"
            height="56"
            alt="The Corner"
          />
          <span>
            THE CORNER <small>PRIVATE MEMBERSHIP</small>
          </span>
          <a href="mailto:admin@coopscorner.tech">Contact your host</a>
        </header>
        <section className="family-card">
          <p className="family-eyebrow">PERSONAL & CONFIDENTIAL</p>
          <div className="family-seal" aria-hidden="true">
            C
          </div>
          <p className="family-script">La nostra famiglia.</p>
          <h1>You’ve been vouched for.</h1>
          <p>
            A private seat at the table. Good information. Clear decisions. A
            family building something together.
          </p>
          {!opened && (
            <button className="family-primary" disabled={busy} onClick={open}>
              {busy ? "Checking your invitation…" : "Open your invitation"}{" "}
              <span aria-hidden="true">↗</span>
            </button>
          )}
          <small>
            Keep this link private. Each invitation can be claimed once.
          </small>
        </section>
        {error && (
          <p className="family-notice" role="alert">
            {error}
          </p>
        )}
        {opened && offer && (
          <>
            <nav className="family-nav" aria-label="Invitation sections">
              <button
                onClick={() =>
                  document.getElementById("your-seat")?.scrollIntoView()
                }
              >
                Your seat
              </button>
              <button
                onClick={() =>
                  document.getElementById("house-rules")?.scrollIntoView()
                }
              >
                House rules
              </button>
              <button
                onClick={() =>
                  document.getElementById("field-guide")?.scrollIntoView()
                }
              >
                Field guide
              </button>
              <button
                onClick={() =>
                  document.getElementById("questions")?.scrollIntoView()
                }
              >
                FAQ
              </button>
              <button
                onClick={() =>
                  document.getElementById("feedback")?.scrollIntoView()
                }
              >
                Feedback
              </button>
            </nav>
            <section id="your-seat" className="family-section">
              <p className="family-eyebrow">
                {offer.cohort === "friend"
                  ? "FIVE FRIEND PLACES · SEPARATE FROM BETA"
                  : "TEN BETA PLACES"}
              </p>
              <h2>{offer.title}</h2>
              <p className="family-lead">{offer.access}</p>
              <p>{offer.pricing}</p>
              <p>
                Beta access ends <strong>{offer.end_label}</strong>. There are
                no automatic charges. Live is a separate future package; it is
                not available just because a rate is reserved.
              </p>
              {offer.cohort === "beta" && !offer.paid && (
                <p>
                  The optional $50 fee covers only the remaining beta period,
                  not a new month from payment. No refunds, subject to
                  applicable law. Request payment instructions only through an
                  enabled checkout in Account; never send funds based on this
                  invitation.
                </p>
              )}
              <div className="family-code">
                <span>YOUR PRIVATE CODE</span>
                <code>{token}</code>
                <button
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(token);
                      setCopied(true);
                    } catch {
                      setCopied(false);
                      setError("Copy the displayed code manually.");
                    }
                  }}
                >
                  {copied ? "Copied" : "Copy code"}
                </button>
              </div>
              <p className="family-muted">
                Claim before{" "}
                {new Date(offer.expires_at * 1000).toLocaleString()}. This is
                the code’s expiry, not your access end date.
                {offer.username &&
                  ` Use the invited username: ${offer.username}.`}
              </p>
            </section>
            <section id="house-rules" className="family-section">
              <p className="family-eyebrow">THE HOUSE RULES</p>
              <h2>Keep it sharp. Keep it responsible.</h2>
              <ul>
                <li>
                  One personal account per invited member. Do not share your
                  code, account or private data, resell access, scrape the
                  service or bypass access controls.
                </li>
                <li>
                  Only participate where you meet the legal age and eligibility
                  requirements. Follow local law and each sportsbook’s rules;
                  never bypass location or identity checks.
                </li>
                <li>
                  This is beta analytics, with possible errors and
                  interruptions. It is not a sportsbook, does not place bets,
                  and does not guarantee winnings or investment returns.
                </li>
                <li>
                  Use only money you can afford to lose. Set spending and time
                  limits before playing. Never borrow, use bill money or chase
                  losses. Pause if gambling causes stress.
                </li>
                <li>
                  Report problems respectfully. Feedback is stored for the
                  operator to review. Do not submit passwords, private keys,
                  payment details or sensitive personal information. No
                  attachments are needed.
                </li>
              </ul>
              <p>
                Membership pricing is the offer above. Invitations do not
                activate live collection or payment processing. Your Account
                page shows your current access. Support:{" "}
                <a href="mailto:admin@coopscorner.tech">
                  admin@coopscorner.tech
                </a>
                .
              </p>
              <label className="family-check">
                <input
                  type="checkbox"
                  checked={eligible}
                  onChange={(e) => setEligible(e.target.checked)}
                />
                I meet the applicable legal age and eligibility requirements and
                understand the risks of gambling.
              </label>
              <label className="family-check">
                <input
                  type="checkbox"
                  checked={agree}
                  onChange={(e) => setAgree(e.target.checked)}
                />
                I have read and accept my membership offer, the beta
                limitations, house rules and feedback handling above.
              </label>
              {accepted ? (
                <div className="family-notice">
                  <strong>Your agreement is recorded.</strong>
                  {offer.claimed ? (
                    <p>
                      Your invitation has been claimed. Your field guide and
                      feedback form remain available here while signed in.
                    </p>
                  ) : status === "signed-in" ? (
                    <p>
                      You are already signed in. Sign out before creating a new
                      invited account. Opening this page does not change your
                      existing membership.
                    </p>
                  ) : (
                    <p>
                      <a
                        className="family-primary"
                        href={`/login#invite=${token}`}
                      >
                        Create your account ↗
                      </a>
                    </p>
                  )}
                </div>
              ) : (
                <button
                  className="family-primary"
                  disabled={
                    busy ||
                    !eligible ||
                    !agree ||
                    (!offer.trial_available &&
                      offer.cohort === "beta" &&
                      !offer.paid)
                  }
                  onClick={accept}
                >
                  Accept & continue
                </button>
              )}
              <p className="family-muted">
                Agreement version {offer.version}. Accepting does not claim your
                seat, start a trial or charge you. Your code is claimed only
                when account creation succeeds. Trial enforcement is activated
                separately by the operator; your Account page shows the
                immutable start and end when active.
              </p>
            </section>
            <section id="field-guide" className="family-section">
              <p className="family-eyebrow">YOUR FIRST NIGHT AT THE TABLE</p>
              <h2>A short field guide.</h2>
              <ol className="family-steps">
                <li>Review your offer and accept the rules.</li>
                <li>
                  Create your account with the prefilled invitation code. Save
                  your password securely.
                </li>
                <li>
                  Open Account to confirm your access, then explore the tools
                  using stored odds.
                </li>
                <li>
                  Verify every selection and price at the sportsbook yourself.
                  Start with research, not bigger stakes.
                </li>
              </ol>
              {lessons.map(([title, body]) => (
                <details key={title}>
                  <summary>{title}</summary>
                  <p>{body}</p>
                </details>
              ))}
              <p className="family-muted">
                A unit is a consistent amount you choose within a discretionary
                budget, not a promise of safety. A small sample can look
                convincing by chance. No tool removes variance or loss risk.
              </p>
            </section>
            <section id="questions" className="family-section">
              <p className="family-eyebrow">BEFORE YOU ASK</p>
              <h2>Good questions. Straight answers.</h2>
              {[
                [
                  "Will I be charged automatically?",
                  "No. This invitation does not start a subscription or send a payment. Any beta payment is an explicit choice with manual verification. Do not transfer crypto until the enabled Account checkout provides a valid quote and instructions.",
                ],
                [
                  "Can I share my invitation?",
                  "Keep it for the person it was issued to. A friend code binds to the first new account that successfully claims it; a specifically named invitation must match its intended username. New beta invitations let you choose your username at signup. It cannot be reused.",
                ],
                [
                  "What happens after my free access?",
                  offer.cohort === "friend"
                    ? "Your complimentary beta ends November 20. Your locked future rates are $25/month standard or $50/month live when that package becomes available. No renewal or live service starts here."
                    : "A trial lasts seven days from its recorded activation, with all beta access ending November 20. Paying the optional $50 beta fee secures the $50/month standard launch rate. Without it, the standard launch rate is $125/month. No automatic renewal starts here.",
                ],
                [
                  "Why are there no bets or no fresh odds?",
                  "The feed may have no qualifying prices, data may be stale, or collection may still be disabled. Read the timestamp and status. The deployed beta uses its scheduled collection policy; this invitation does not authorize a paid refresh.",
                ],
                [
                  "Can I install it on my iPhone?",
                  "Yes. Open the site in Safari, tap Share, then Add to Home Screen. You can also use it in the browser.",
                ],
                [
                  "I forgot my password or my code expired.",
                  "Contact admin@coopscorner.tech for help. Never send your password, wallet seed phrase or private keys. Your host can review an expired or revoked invitation.",
                ],
                [
                  "How do I report a problem?",
                  "Use the form below. Include the tool, device/browser, what you expected, what happened, and steps to repeat it. Redact private details. Feedback is reviewed by the operator, not monitored as emergency support.",
                ],
              ].map(([title, body]) => (
                <details key={title}>
                  <summary>{title}</summary>
                  <p>{body}</p>
                </details>
              ))}
            </section>
            <section id="feedback" className="family-section">
              <p className="family-eyebrow">HELP BUILD THE FAMILY BUSINESS</p>
              <h2>Tell us what needs work.</h2>
              <form onSubmit={feedback}>
                <label>
                  Type
                  <select name="category">
                    <option value="bug">Bug / something broke</option>
                    <option value="feature">Feature request</option>
                    <option value="data">Data or odds concern</option>
                    <option value="question">Question</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label>
                  Short title
                  <input
                    name="title"
                    required
                    maxLength={120}
                    placeholder="Example: Props filter is clipped on iPhone"
                  />
                </label>
                <label>
                  Details
                  <textarea
                    name="message"
                    required
                    maxLength={4000}
                    rows={5}
                    placeholder="Tool, device, steps, expected result, actual result. No passwords or wallet secrets."
                  />
                </label>
                <button className="family-primary" disabled={busy}>
                  Send feedback
                </button>
                <p role="status">{receipt}</p>
              </form>
              <p className="family-muted">
                After claiming the invitation, sign in to that account to use
                this form. Before claiming, a valid private link is required. Up
                to five reports per hour.
              </p>
            </section>
          </>
        )}
        <footer className="family-footer">
          <p>THE CORNER · INFORMATION, NOT GUARANTEES.</p>
          <p>
            Learn more:{" "}
            <a
              href="https://www.responsiblegambling.org/for-the-public/problem-gambling-prevention/plan-before-you-play/"
              target="_blank"
              rel="noreferrer"
            >
              Plan before you play
            </a>{" "}
            ·{" "}
            <a
              href="https://support.betfair.com/app/answers/detail/exchange-general-rules"
              target="_blank"
              rel="noreferrer"
            >
              Why settlement rules matter
            </a>
          </p>
          <small>
            An original private-club invitation. No affiliation with any
            television production.
          </small>
        </footer>
      </div>
    </main>
  );
}
