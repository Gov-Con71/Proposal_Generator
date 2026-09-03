import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  output: 'standalone', //added for docker
  reactStrictMode: true,

  // Fix: allow network access from other devices on your LAN during dev
  allowedDevOrigins: ['192.168.62.32'],

  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: process.env.NEXT_PUBLIC_API_HOSTNAME || 'api.proposalai.com',
      },
    ],
  },

  env: {
    NEXT_PUBLIC_APP_NAME: 'ProposalAI',
    NEXT_PUBLIC_APP_VERSION: '0.1.0',
  },

  // No redirect off '/' any more: it serves the public marketing landing page.
  // A config-level redirect here would win before routing ever reached
  // app/page.tsx, so the page would be unreachable no matter what it contained.
  // Signed-in users reach the app through the header, and the proxy sends
  // anyone hitting a guarded route to /login with a ?from= to return to.

  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options',        value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy',        value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy',     value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ]
  },
}

export default nextConfig