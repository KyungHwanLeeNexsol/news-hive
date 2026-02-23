import type { Metadata } from "next";
import "./globals.css";
import Header from "@/components/Header";

export const metadata: Metadata = {
  title: "Stock News Tracker",
  description: "섹터 기반 투자 뉴스 추적",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="bg-gray-50 min-h-screen">
        <Header />
        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
