import type { Metadata, Viewport } from "next";
import "../../frontend/styles.css";
import "../../frontend/betting.css";
import "../../frontend/corner.css";
import "./stored-odds.css";
import "./personal.css";
import "./auth.css";
import { AuthGate, AuthProvider } from "../components/auth-provider";

export const metadata: Metadata = {
  title: "The Corner — Sports market intelligence",
  description: "The Corner betting workspace. Local fixture market analysis.",
  // The tab icon is a 64px rendition (a few KB) of the brand logo; the 600 KB original is never downloaded for it.
  icons: { icon: "/_next/image?url=%2Fassets%2Fcorner-logo.png&w=64&q=75" },
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
      <body>
        <AuthProvider>
          <AuthGate>{children}</AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
