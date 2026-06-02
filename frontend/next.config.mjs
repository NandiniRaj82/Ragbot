/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required for the multi-stage Docker build which copies .next/standalone
  output: "standalone",

  // Proxy /api/* → backend so the browser never needs to know the backend URL.
  // BACKEND_URL is a server-side env var set at runtime in Docker.
  async rewrites() {
    const backend = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "https://ragbot-production-f48d.up.railway.app";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },

  // Allow Next.js Image to load thumbnails from known video CDNs
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "i.ytimg.com" },
      { protocol: "https", hostname: "i9.ytimg.com" },
      { protocol: "https", hostname: "img.youtube.com" },
      { protocol: "https", hostname: "*.cdninstagram.com" },
      { protocol: "https", hostname: "scontent.cdninstagram.com" },
      { protocol: "https", hostname: "scontent-*.cdninstagram.com" },
    ],
  },
};

export default nextConfig;
