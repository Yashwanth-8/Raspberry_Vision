import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disable StrictMode: this app uses camera hardware + MediaPipe WASM which
  // cannot handle React's intentional double-mount in development.
  reactStrictMode: false,
  reactCompiler: true,
};

export default nextConfig;
