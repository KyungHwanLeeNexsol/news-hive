/**
 * Telegram 웹훅 프록시 라우트.
 * Telegram → Vercel(HTTPS) → FastAPI 백엔드로 중계한다.
 * /api/* 경로는 next.config.ts rewrite로 FastAPI에 프록시되므로
 * 이 라우트는 /tg-webhook 경로를 사용한다.
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL ?? 'http://localhost:8000';

export async function POST(request: NextRequest): Promise<NextResponse> {
  const secretToken = request.headers.get('x-telegram-bot-api-secret-token');
  const body = await request.text();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (secretToken) {
    headers['x-telegram-bot-api-secret-token'] = secretToken;
  }

  const response = await fetch(`${BACKEND_URL}/api/following/telegram/webhook`, {
    method: 'POST',
    headers,
    body,
  });

  const data: unknown = await response.json();
  return NextResponse.json(data, { status: response.status });
}
