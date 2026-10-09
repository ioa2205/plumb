import "server-only";

import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

import { one, run } from "./db";

export const SESSION_COOKIE = "tandir_session";

export type Role = "customer" | "courier" | "branch_manager" | "admin";

export const STAFF: readonly Role[] = ["admin", "branch_manager"];

/** The signed-in person. A class, so a whole record is never handed to a Client Component by accident. */
export class Viewer {
  constructor(
    readonly id: number,
    readonly role: Role,
    readonly branchId: number | null,
    readonly displayName: string,
  ) {}

  is(...roles: Role[]): boolean {
    return roles.includes(this.role);
  }
}

type ViewerRow = { id: number; role: Role; branch_id: number | null; display_name: string };

export function viewerForToken(token: string | undefined): Viewer | null {
  if (!token) return null;
  const row = one<ViewerRow>(
    `SELECT users.id, users.role, users.branch_id, users.display_name
       FROM sessions JOIN users ON users.id = sessions.user_id
      WHERE sessions.token = ?`,
    token,
  );
  return row ? new Viewer(row.id, row.role, row.branch_id, row.display_name) : null;
}

// Same format as the API lab: scrypt$<salt hex>$<digest hex>, N=2^14, r=8, p=1, 64 bytes.
export function verifyPassword(password: string, stored: string): boolean {
  const [scheme, saltHex, digestHex] = stored.split("$");
  if (scheme !== "scrypt" || !saltHex || !digestHex) return false;
  const expected = Buffer.from(digestHex, "hex");
  const actual = scryptSync(password, Buffer.from(saltHex, "hex"), expected.length, {
    N: 2 ** 14,
    r: 8,
    p: 1,
  });
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

type LoginRow = { id: number; role: Role; password_hash: string };

/** Checks the password and opens a session; null when either is wrong. */
export function openSession(username: string, password: string): { token: string; role: Role } | null {
  const user = one<LoginRow>(
    "SELECT id, role, password_hash FROM users WHERE username = ?",
    username,
  );
  if (!user || !verifyPassword(password, user.password_hash)) return null;
  const token = randomBytes(32).toString("base64url");
  run(
    "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
    token,
    user.id,
    new Date().toISOString(),
  );
  return { token, role: user.role };
}

export function closeSession(token: string): void {
  run("DELETE FROM sessions WHERE token = ?", token);
}
