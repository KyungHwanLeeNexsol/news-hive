import type { Metadata } from "next";
import "./globals.css";
import Header from "@/components/Header";
import MacroAlertBanner from "@/components/MacroAlertBanner";

export const metadata: Metadata = {
  title: "NewsHive",
  description: "업종 단위로 종목 뉴스를 모아 놓치기 쉬운 투자 정보를 포착",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <head>
        <link
          rel="stylesheet"
          as="style"
          crossOrigin="anonymous"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css"
        />
      </head>
      <body className="bg-[#f6f6f6] min-h-screen font-[Pretendard,sans-serif]">
        <Header />
        <main className="max-w-[1200px] mx-auto px-4 py-4">
          <MacroAlertBanner />
          {children}
        </main>
      </body>
    </html>
  );
}
