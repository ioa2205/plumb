import type { NextRequest } from "next/server";

import { all } from "@/lib/db";
import { SESSION_COOKIE, viewerForToken } from "@/lib/sessions";

export function GET(request: NextRequest): Response {
  const viewer = viewerForToken(request.cookies.get(SESSION_COOKIE)?.value);
  if (!viewer) return Response.json({ detail: "Sign in first" }, { status: 401 });
  if (!viewer.is("admin")) return Response.json({ detail: "Not allowed" }, { status: 403 });
  const rows = all<{ branch: string; orders: number; total_cents: number }>(
    `SELECT branches.name AS branch, COUNT(orders.id) AS orders,
            COALESCE(SUM(orders.total_cents), 0) AS total_cents
       FROM branches LEFT JOIN orders ON orders.branch_id = branches.id
      GROUP BY branches.id
      ORDER BY branches.id`,
  );
  return Response.json(rows);
}
