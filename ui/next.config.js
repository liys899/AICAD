/** @type {import('next').NextConfig} */
// 与 backend/api.py 默认端口一致（Flask debug默认 5001）
const backend = process.env.CQASK_BACKEND_URL?.replace(/\/$/, "") || "http://127.0.0.1:5001"

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
