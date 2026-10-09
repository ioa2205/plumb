import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, viewerForToken } from "@/lib/sessions";

// Admin-only API routes are gated here, before the route runs.
export function proxy(request: NextRequest): Response {
  const viewer = viewerForToken(request.cookies.get(SESSION_COOKIE)?.value);
  if (!viewer) return Response.json({ detail: "Sign in first" }, { status: 401 });
  if (!viewer.is("admin")) return Response.json({ detail: "Not allowed" }, { status: 403 });
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/admin/export"],
};
