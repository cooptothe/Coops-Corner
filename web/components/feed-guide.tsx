import Link from "next/link";
import type { View } from "../lib/contracts";
export function FeedGuide({ view }: { view: View }) {
  return (
    <Link className="tool-help" href={`/help#${view}`}>
      Help &amp; guide
    </Link>
  );
}
