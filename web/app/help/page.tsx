import type { Metadata } from "next";
import HelpPage from "../../components/help-page";
export const metadata: Metadata = { title: "Help & guide — The Corner" };
export default function Page() {
  return <HelpPage />;
}
