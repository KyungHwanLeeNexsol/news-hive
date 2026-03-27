import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const pathname = request.nextUrl.pathname;

  // /maintenance 페이지, API 라우트, Next.js 내부 경로, 정적 파일은 통과
  if (
    pathname.startsWith("/maintenance") ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // 백엔드 헬스체크 — 2초 타임아웃 (AbortController: Edge Runtime 호환)
  const backendUrl =
    process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2000);
  try {
    const res = await fetch(`${backendUrl}/api/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    clearTimeout(timer);
    if (res.ok) return NextResponse.next();
  } catch {
    // 연결 실패 또는 타임아웃 (서버 재시작 중)
  } finally {
    clearTimeout(timer);
  }

  return NextResponse.redirect(new URL("/maintenance", request.url));
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
