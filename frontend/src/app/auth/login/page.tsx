'use client';

import { useState, FormEvent, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/components/AuthProvider';

/** 로그인 폼 UI — searchParams 의존으로 Suspense 필요 */
function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, isLoggedIn } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  // 이메일 인증 완료 후 이동 시 성공 메시지 표시
  useEffect(() => {
    if (searchParams.get('verified') === '1') {
      setSuccess('이메일 인증이 완료되었습니다. 로그인해 주세요.');
    }
  }, [searchParams]);

  // 이미 로그인된 경우 홈으로 이동
  useEffect(() => {
    if (isLoggedIn) {
      router.replace('/');
    }
  }, [isLoggedIn, router]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      await login(email, password);
      router.replace('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인에 실패했습니다.');
    } finally {
      setLoading(false);
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

        <h1 className="text-xl font-bold text-gray-900 text-center mb-6">로그인</h1>

        {/* 성공 메시지 */}
        {success && (
          <div className="mb-4 px-3 py-2.5 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
            {success}
          </div>
        )}

        {/* 에러 메시지 */}
        {error && (
          <div className="mb-4 px-3 py-2.5 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
              이메일
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              placeholder="example@email.com"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm outline-none focus:border-[#1261c4] focus:ring-1 focus:ring-[#1261c4] transition"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
              비밀번호
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              placeholder="비밀번호 입력"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm outline-none focus:border-[#1261c4] focus:ring-1 focus:ring-[#1261c4] transition"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-[#1261c4] hover:bg-[#0e52a8] text-white text-sm font-semibold rounded-lg transition disabled:opacity-60 disabled:cursor-not-allowed mt-2"
          >
            {loading ? '로그인 중...' : '로그인'}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-gray-500">
          계정이 없으신가요?{' '}
          <Link href="/auth/register" className="text-[#1261c4] font-medium hover:underline">
            회원가입
          </Link>
        </p>
      </div>
    </div>
  );
}

/**
 * 로그인 페이지.
 * useSearchParams 사용으로 Suspense 래핑이 필요하다.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-[calc(100vh-48px)]"><span className="text-gray-400 text-sm">로딩 중...</span></div>}>
      <LoginContent />
    </Suspense>
  );
}
