import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Only rewrite requests starting with /api/
  if (pathname.startsWith("/api/")) {
    // Read the backend URL at runtime (injected by Railway to the running container)
    const backendUrl =
      process.env.NEXT_PUBLIC_API_URL ||
      process.env.BACKEND_URL ||
      "http://localhost:8000";

    // Construct the new target URL pointing to the backend service
    const targetUrl = new URL(pathname + search, backendUrl);

    return NextResponse.rewrite(targetUrl);
  }
}

export const config = {
  matcher: "/api/:path*",
};
