import { cpSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { inject } from "vitest";

import { closeDb, one } from "@/lib/db";
import { openSession, SESSION_COOKIE } from "@/lib/sessions";

import { jar } from "./jar";

// Lab fixture passwords, published on purpose (labs/tandir/api/tandir/seed.py).
export const PASSWORDS: Record<string, string> = {
  alice: "alice-lab-pass",
  bob: "bob-lab-pass",
  kamol: "kamol-lab-pass",
  farrukh: "farrukh-lab-pass",
  nodira: "nodira-lab-pass",
  admin: "admin-lab-pass",
};

/** A fresh copy of the seeded lab database for one test; returns its teardown. */
export function freshLab(): () => void {
  closeDb();
  jar.clear();
  const dataDir = mkdtempSync(path.join(tmpdir(), "tandir-web-"));
  cpSync(inject("seededDataDir"), dataDir, { recursive: true });
  process.env.TANDIR_DATA_DIR = dataDir;
  return () => {
    closeDb();
    rmSync(dataDir, { recursive: true, force: true });
  };
}

export function tokenFor(username: string): string {
  const session = openSession(username, PASSWORDS[username] ?? "");
  if (!session) throw new Error(`cannot sign in as ${username}`);
  return session.token;
}

/** Make the next server call arrive with this user's session cookie. */
export function signInAs(username: string): string {
  const token = tokenFor(username);
  jar.set(SESSION_COOKIE, token);
  return token;
}

export function signOutAll(): void {
  jar.clear();
}

export function orderStatus(orderId: number): string | undefined {
  return one<{ status: string }>("SELECT status FROM orders WHERE id = ?", orderId)?.status;
}

export function form(fields: Record<string, string | number>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, String(value));
  return data;
}
