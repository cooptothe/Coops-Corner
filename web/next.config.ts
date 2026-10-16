import type { NextConfig } from "next";
import { resolve } from "node:path";

// Keep browser requests same-origin. Do not accept an arbitrary upstream or expose secrets.
const apiOrigin = process.env.CORNER_API_ORIGIN ?? "http://127.0.0.1:8765";
const parsed = new URL(apiOrigin);
const refresh = new URL(
  process.env.CORNER_REFRESH_ORIGIN ?? "http://127.0.0.1:8766",
);
if (
  !["127.0.0.1", "localhost", "[::1]"].includes(refresh.hostname) ||
  refresh.protocol !== "http:" ||
  refresh.username ||
  refresh.password ||
  refresh.pathname !== "/" ||
  refresh.search ||
  refresh.hash
) {
  throw new Error(
    "CORNER_REFRESH_ORIGIN must be a plain loopback HTTP origin.",
  );
}
if (
  !["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname) ||
  parsed.protocol !== "http:" ||
  parsed.username ||
  parsed.password ||
  parsed.pathname !== "/" ||
  parsed.search ||
  parsed.hash
) {
  throw new Error("CORNER_API_ORIGIN must be a plain loopback HTTP origin.");
}
// A tunnel such as ngrok reaches the dev server under its own host name. Next's dev server only serves hot reload and
// dev resources to hosts it is told about, so the exact hosts of CORNER_PUBLIC_ORIGINS (https only) are listed.
const publicHosts = (process.env.CORNER_PUBLIC_ORIGINS ?? "")
  .split(",")
  .map((item) => item.trim())
  .flatMap((item) => {
    try {
      const url = new URL(item);
      return url.protocol === "https:" && url.hostname ? [url.hostname] : [];
    } catch {
      return [];
    }
  });
const config: NextConfig = {
  // Keep disposable UI checks isolated from an operator's running dev server.
  distDir: process.env.CORNER_UI_REVIEW === "1" ? ".next-ui-review" : ".next",
  turbopack: { root: resolve(process.cwd(), "..") },
  allowedDevOrigins: publicHosts,
  // A multi-league refresh takes over a minute; the default proxy timeout is 30 seconds.
  experimental: { proxyTimeout: 300000 },
  async rewrites() {
    return [
      {
        source: "/api/refresh/v1/:path*",
        destination: `${refresh.origin}/api/refresh/v1/:path*`,
      },
      {
        source: "/api/v1/sports/:path*",
        destination: "http://127.0.0.1:8080/api/v1/sports/:path*",
      },
      {
        source: "/api/account/v1/:path*",
        destination: "http://127.0.0.1:8080/api/account/v1/:path*",
      },
      {
        source: "/api/market/v1/:path*",
        destination: "http://127.0.0.1:8080/api/market/v1/:path*",
      },
      {
        source: "/api/v1/:path*",
        destination: `${parsed.origin}/api/v1/:path*`,
      },
    ];
  },
};
export default config;
