import { beforeEach, describe, expect, it } from "vitest";

import { one } from "@/lib/db";
import { openSession, verifyPassword, viewerForToken } from "@/lib/sessions";

import { freshLab, PASSWORDS } from "./support/lab";

beforeEach(freshLab);

describe("sign-in shared with the API lab", () => {
  it.each(Object.keys(PASSWORDS))("verifies the scrypt hash the Python seed wrote for %s", (username) => {
    const row = one<{ password_hash: string }>("SELECT password_hash FROM users WHERE username = ?", username);
    expect(row).toBeDefined();
    expect(verifyPassword(PASSWORDS[username] ?? "", row?.password_hash ?? "")).toBe(true);
    expect(verifyPassword("wrong", row?.password_hash ?? "")).toBe(false);
  });

  it("opens a session that resolves to the right person", () => {
    const session = openSession("farrukh", "farrukh-lab-pass");
    expect(session?.role).toBe("branch_manager");
    const viewer = viewerForToken(session?.token);
    expect(viewer?.displayName).toBe("Farrukh Manager");
    expect(viewer?.branchId).toBe(1);
  });

  it.each([
    ["alice", "nope"],
    ["zara", "alice-lab-pass"],
    ["alice", ""],
  ])("refuses %s with a wrong password or unknown name", (username, password) => {
    expect(openSession(username, password)).toBeNull();
  });

  it.each([undefined, "", "not-a-session"])("treats token %s as signed out", (token) => {
    expect(viewerForToken(token)).toBeNull();
  });

  it("refuses malformed stored hashes", () => {
    expect(verifyPassword("x", "plain")).toBe(false);
    expect(verifyPassword("x", "bcrypt$00$00")).toBe(false);
  });
});
