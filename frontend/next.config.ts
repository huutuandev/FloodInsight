import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    const apiUrl = process.env.FLOODINSIGHT_API_URL;
    if (!apiUrl) return [];

    return [{ source: "/api/health", destination: new URL("/health", apiUrl).href }];
  },
};

export default config;
