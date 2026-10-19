import type { Metadata } from "next";
import InvitationPage from "../../components/invitation-page";
import "./invitation.css";
export const metadata: Metadata = {
  title: "A private invitation — The Corner",
  description: "Your seat at The Corner. A private invitation to the family.",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};
export default function Page() {
  return <InvitationPage />;
}
