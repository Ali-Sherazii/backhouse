import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Backhouse",
  description: "Supplier invoice processing for restaurants, hotels and cafés",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
