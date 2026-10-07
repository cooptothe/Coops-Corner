import { notFound } from "next/navigation";
import Workspace from "../../components/workspace";
import { VIEWS, type View } from "../../lib/contracts";
export default async function Page({
  params,
}: {
  params: Promise<{ view: string }>;
}) {
  const { view } = await params;
  if (!VIEWS.includes(view as View)) notFound();
  return <Workspace view={view as View} />;
}
