import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@fontsource-variable/manrope";
import "./globals.css";

export const metadata: Metadata = {
  title: "FloodInsight Da Nang",
  description: "Experimental flood risk monitoring, forecast evidence, and rainfall analytics for Da Nang",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
