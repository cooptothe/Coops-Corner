import type { Metadata, Viewport } from "next";
import "../../frontend/styles.css";
import "../../frontend/betting.css";
import "../../frontend/corner.css";
import "./stored-odds.css";
import "./personal.css";

export const metadata: Metadata = {
  title: "The Corner — Sports market intelligence",
  description: "The Corner betting workspace. Local fixture market analysis.",
  icons: { icon: "/assets/corner-logo.png" },
};
export const viewport: Viewport = {
  themeColor: "#b51c2a",
  width: "device-width",
  initialScale: 1,
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
