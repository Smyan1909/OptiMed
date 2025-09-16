import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Point to the request config we added under src/i18n/request.ts
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

const nextConfig: NextConfig = {
  eslint: {
    // Do not fail the production build on ESLint issues
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    if (process.env.NODE_ENV === "development") {
      return [
        {
          source: "/api/:path*",
          destination: "http://localhost:8000/:path*",
        },
      ];
    }
    // In production, do not rewrite. API routes call the backend via API_BASE_URL.
    return [];
  },
};

export default withNextIntl(nextConfig);
