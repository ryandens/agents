import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { AuthProvider } from "./components/AuthProvider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Kitchen Agent",
  description: "AI-powered meal planning and kitchen management agent",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <nav className="shrink-0 flex items-center gap-1 px-4 py-2 bg-white dark:bg-stone-900 border-b border-stone-200 dark:border-stone-800">
          <span className="text-lg mr-2">🥗</span>
          <Link
            href="/"
            className="px-3 py-1.5 text-sm font-medium rounded-lg text-stone-700 dark:text-stone-300 hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
          >
            Chat
          </Link>
          <Link
            href="/pantry"
            className="px-3 py-1.5 text-sm font-medium rounded-lg text-stone-700 dark:text-stone-300 hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
          >
            Pantry
          </Link>
        </nav>
        <AuthProvider>
          <div className="flex-1 flex flex-col min-h-0">{children}</div>
        </AuthProvider>
      </body>
    </html>
  );
}
