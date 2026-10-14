import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Casino Bonus Comparison",
  description: "Welcome bonuses scraped from a public comparison page and structured for review.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
