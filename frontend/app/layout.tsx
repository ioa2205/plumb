import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource/atkinson-hyperlegible-next/latin-400.css";
import "@fontsource/atkinson-hyperlegible-next/latin-500.css";
import "@fontsource/atkinson-hyperlegible-next/latin-600.css";
import "@fontsource/atkinson-hyperlegible-next/latin-700.css";
import "@fontsource/atkinson-hyperlegible-mono/latin-400.css";
import "@fontsource/atkinson-hyperlegible-mono/latin-500.css";
import "@fontsource/atkinson-hyperlegible-mono/latin-600.css";
import { GlyphSprite } from "../components/Glyph";
import "./tokens.css";
import "./globals.css";

export const metadata: Metadata = { title: "Plumb · Security evidence", description: "Local security investigation with cited source and saved evidence.", icons: { icon: "/favicon.svg" } };

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body><GlyphSprite />{children}</body></html>;
}
