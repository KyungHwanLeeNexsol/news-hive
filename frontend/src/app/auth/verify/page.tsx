'use client';

import { useState, useEffect, FormEvent, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { verifyEmail, resendVerification } from '@/lib/api';

/** 이메일 인증 UI — searchParams 의존으로 Suspense 필요 */
function VerifyContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams.get('email') ?? '';

  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // 재발송 쿨다운 (60초)
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError('');
    if (code.length !== 6) {
      setError('6자리 인증 코드를 입력해 주세요.');
      return;
    }
    setLoading(true);
    try {
      await verifyEmail(email, code);
      // 로그인 페이지로 이동하며 성공 메시지 전달
      router.push('/auth/login?verified=1');
    } catch (err) {
      setError(err instanceof Error ? err.message : '인증에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    if (cooldown > 0) return;
    setError('');
    try {
      await resendVerification(email);
      setCooldown(60);
    } catch (err) {
      setError(err instanceof Error ? err.message : '재발송에 실패했습니다.');
    }
  }

  return (
    <div className="min-h-[calc(100vh-48px)] flex items-center justify-center py-8">
      <div className="w-full max-w-sm bg-white rounded-xl border border-gray-200 shadow-sm p-8">
        {/* 로고 */}
        <div className="flex items-center justify-center gap-2 mb-6">
          <svg width="24" height="24" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M16 2L28.124 9V23L16 30L3.876 23V9L16 2Z" fill="#1261c4"/>
            <path d="M16 5.5L25.5 10.75V21.25L16 26.5L6.5 21.25V10.75L16 5.5Z" fill="#ffffff" fillOpacity="0.15"/>
            <path d="M10 21V11h2.8l6.4 8V11H22v10h-2.8l-6.4-8v8H10Z" fill="#ffffff"/>
          </svg>
          <span className="text-[17px] font-bold text-[#1261c4] tracking-tight">NewsHive</span>
        </div>

        <h1 className="text-xl font-bold text-gray-900 text-center mb-2">이메일 인증</h1>
        <p className="text-sm text-gray-500 text-center mb-6">
          <span className="font-medium text-gray-700">{email || '입력하신 이메일'}</span>로<br />
          발송된 6자리 인증 코드를 입력해 주세요.
        </p>

        {/* 에러 메시지 */}
        {error && (
          <div className="mb-4 px-3 py-2.5 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="code" className="block text-sm font-medium text-gray-700 mb-1">
              인증 코드
            </label>
            <input
              id="code"
              type="text"
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              required
              placeholder="123456"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-center tracking-[0.3em] outline-none focus:border-[#1261c4] focus:ring-1 focus:ring-[#1261c4] transition"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-[#1261c4] hover:bg-[#0e52a8] text-white text-sm font-semibold rounded-lg transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {loading ? '확인 중...' : '인증하기'}
          </button>
        </form>

        {/* 재발송 버튼 */}
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={handleResend}
            disabled={cooldown > 0}
            className="text-sm text-gray-500 hover:text-[#1261c4] disabled:text-gray-300 disabled:cursor-not-allowed transition"
          >
            {cooldown > 0 ? `재발송 (${cooldown}초 후 가능)` : '인증 코드 재발송'}
          </button>
        </div>

        <p className="mt-5 text-center text-sm text-gray-500">
          <Link href="/auth/login" className="text-[#1261c4] font-medium hover:underline">
            로그인으로 돌아가기
          </Link>
        </p>
      </div>
    </div>
  );
}

/**
 * 이메일 인증 페이지.
 * useSearchParams 사용으로 Suspense 래핑이 필요하다.
 */
export default function VerifyPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-[calc(100vh-48px)]"><span className="text-gray-400 text-sm">로딩 중...</span></div>}>
      <VerifyContent />
    </Suspense>
  );
}
