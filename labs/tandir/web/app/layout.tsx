import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { getViewer } from "@/lib/dal";

import { signOut } from "./login/actions";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tandir (Plumb lab)",
  description: "A deliberately vulnerable bakery-ordering lab for Plumb. Loopback only.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const viewer = await getViewer();
  return (
    <html lang="en">
      <body>
        <p className="lab-note">Plumb lab application with intentional flaws. Loopback only.</p>
        <nav className="bar">
          <strong>
            <Link href="/">Tandir</Link>
          </strong>
          {viewer?.is("customer") && <Link href="/orders">My orders</Link>}
          {viewer?.is("courier") && <Link href="/courier">Deliveries</Link>}
          {viewer?.is("admin", "branch_manager") && <Link href="/backoffice">Back office</Link>}
          {viewer ? (
            <form action={signOut}>
              <span className="muted">{viewer.displayName} </span>
              <button type="submit">Sign out</button>
            </form>
          ) : (
            <Link href="/login">Sign in</Link>
          )}
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
