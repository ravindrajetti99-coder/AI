import type { Metadata, Viewport } from "next";

import "./globals.css";

import { AuthProvider } from "@/components/auth";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: { default: "EduVerse AI", template: "%s · EduVerse AI" },
  description: "Your AI teacher, mentor, examiner, coding assistant, language partner and career guide.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#4f46e5" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <AuthProvider>
          <Nav />
          <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
