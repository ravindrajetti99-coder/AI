import type { NextConfig } from "next";

// The browser only ever talks to this origin: /api/* is proxied to the FastAPI service,
// so the httpOnly refresh cookie stays first-party and no CORS is needed.
const apiUrl = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
        ],
      },
      // These URLs carry a secret (reset or verification token, invite code): never leak them
      // in a Referer header. Later entries override the default above.
      ...["/reset-password", "/verify-email", "/register"].map((source) => ({ source, headers: [{ key: "Referrer-Policy", value: "no-referrer" }] })),
    ];
  },
};

export default nextConfig;
