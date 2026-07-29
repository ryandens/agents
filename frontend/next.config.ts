import type { NextConfig } from "next";

// In production the static export is served by the FastAPI backend, so the app and the
// API share an origin and `/api/...` resolves without a prefix. `next dev` serves the
// app on its own port, so proxy `/api` to the local backend to keep that true in dev.
// Rewrites are an unsupported feature of `output: "export"`, hence the dev-only guard —
// `next dev` still warns about the combination, which is expected and safe here because
// nothing but the dev server ever applies them.
const devProxy: Pick<NextConfig, "rewrites" | "skipTrailingSlashRedirect"> =
  process.env.NODE_ENV === "development"
    ? {
        // `trailingSlash` would otherwise 308 `/api/pantry` to `/api/pantry/` before the
        // rewrite runs, and the backend's routes have no trailing slash.
        skipTrailingSlashRedirect: true,
        rewrites: async () => [
          {
            source: "/api/:path*",
            destination: `${process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000"}/api/:path*`,
          },
        ],
      }
    : {};

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  ...devProxy,
};

export default nextConfig;
