import type { Metadata } from "next";
import "./globals.css";

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
      <body>{children}</body>
    </html>
  );
}
