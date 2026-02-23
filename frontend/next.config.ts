import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  // Docker 배포 시에만 standalone 사용 (Vercel은 자체 빌드 시스템 사용)
  ...(process.env.DOCKER_BUILD === "true" ? { output: "standalone" as const } : {}),
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
