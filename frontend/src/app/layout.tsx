import type { Metadata } from "next";
import "./globals.css";
import Header from "@/components/Header";

export const metadata: Metadata = {
  title: "증권 뉴스 트래커",
  description: "섹터 기반 투자 뉴스 추적",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="bg-[#f6f6f6] min-h-screen">
        <Header />
        <main className="max-w-[1200px] mx-auto px-4 py-4">{children}</main>
      </body>
    </html>
  );
}
