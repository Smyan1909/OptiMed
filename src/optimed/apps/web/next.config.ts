import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Point to the request config we added under src/i18n/request.ts
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*", // your FastAPI URL
      },
    ];
  },
};

export default withNextIntl(nextConfig);
