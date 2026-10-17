import type { Metadata } from "next";
import LabPage from "../../components/lab-page";
export const metadata: Metadata = { title: "The Lab — The Corner" };
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ bet?: string | string[] }>;
}) {
  const params = await searchParams;
  const selected =
    typeof params.bet === "string" && params.bet.length <= 500
      ? params.bet
      : null;
  return <LabPage selectedBetId={selected} />;
}
