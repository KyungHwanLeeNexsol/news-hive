import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Middleware는 더 이상 백엔드 헬스체크를 하지 않음.
 * Vercel Edge Runtime에서 외부 HTTP IP로의 fetch가 불안정하여
 * 백엔드가 정상인데도 /maintenance로 리디렉션되는 문제가 있었음.
 *
 * 대신 클라이언트 사이드에서 api.ts의 fetchWithRetry가
 * 502/503/네트워크 오류 시 /maintenance로 리디렉션함.
 */
export async function middleware(request: NextRequest): Promise<NextResponse> {
  const pathname = request.nextUrl.pathname;

  // /maintenance 페이지에 있는데 API가 정상이면 홈으로 보내는 것은
  // maintenance/page.tsx의 클라이언트 로직이 처리함
  if (pathname.startsWith("/maintenance")) {
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
