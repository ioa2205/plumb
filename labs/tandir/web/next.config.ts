import type { NextConfig } from "next";

const config: NextConfig = {
  // A lab app: no telemetry headers, no image optimizer, nothing fetched at build time.
  poweredByHeader: false,
  images: { unoptimized: true },
};

export default config;
