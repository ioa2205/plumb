"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { closeSession, openSession, type Role, SESSION_COOKIE } from "@/lib/sessions";

const HOME: Record<Role, string> = {
  customer: "/orders",
  courier: "/courier",
  branch_manager: "/backoffice",
  admin: "/backoffice",
};

export type SignInState = { error: string | null };

export async function signIn(_state: SignInState, formData: FormData): Promise<SignInState> {
  const session = openSession(String(formData.get("username") ?? ""), String(formData.get("password") ?? ""));
  if (!session) return { error: "Wrong username or password" };
  (await cookies()).set(SESSION_COOKIE, session.token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
  });
  redirect(HOME[session.role]);
}

export async function signOut(): Promise<void> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  if (token) closeSession(token);
  store.delete(SESSION_COOKIE);
  redirect("/");
}
