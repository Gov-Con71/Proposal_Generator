import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PUBLIC_ROUTES = ['/login', '/request-access']

// The marketing landing page. Matched EXACTLY, never by prefix: '/' is a prefix
// of every path on the site, so adding it to PUBLIC_ROUTES above would make
// `startsWith` return true for everything and silently disable the guard.
const PUBLIC_EXACT = ['/']

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Allow public routes through
  if (PUBLIC_EXACT.includes(pathname)) {
    return NextResponse.next()
  }
  if (PUBLIC_ROUTES.some((route) => pathname.startsWith(route))) {
    return NextResponse.next()
  }

  // A routing hint, not a credential.
  //
  // This used to read `proposalai-token`, an actual access token the client
  // wrote with document.cookie — which meant the credential was readable by
  // any script on the page. The real refresh token is now an HttpOnly cookie
  // set by the API origin, which this middleware (running on the frontend
  // origin) cannot see and should not need to: enforcement belongs to the API,
  // which rejects every request without a valid bearer token. All this does is
  // save a signed-out visitor from watching a dashboard render and then empty.
  //
  // Forging it grants nothing but the chance to see an empty shell.
  const authed = request.cookies.get('proposalai-authed')?.value

  if (!authed) {
    const loginUrl = new URL('/login', request.url)
    loginUrl.searchParams.set('from', pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|fonts|logo.svg).*)',
  ],
}