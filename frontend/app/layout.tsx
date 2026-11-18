import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@fontsource-variable/manrope";
import "./globals.css";

export const metadata: Metadata = {
  title: "FloodInsight Da Nang",
  description: "Environmental monitoring, rainfall analytics, and modeled weather for Da Nang",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
