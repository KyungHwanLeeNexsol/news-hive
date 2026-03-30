'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { verifyEmail, resendVerification } from '@/lib/api';

/** 이메일 인증 UI — searchParams 의존으로 Suspense 필요 */
function VerifyContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get('token');
  const email = searchParams.get('email') ?? '';

  // 토큰이 있는 경우: 자동 인증 처리
  const [status, setStatus] = useState<'idle' | 'verifying' | 'success' | 'error'>(
    token ? 'verifying' : 'idle',
  );
  const [errorMsg, setErrorMsg] = useState('');

  // 재발송 쿨다운 (60초)
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (!token) return;

    // 토큰 자동 인증
    verifyEmail(token)
      .then(() => {
        setStatus('success');
        // 2초 후 로그인 페이지로 이동
        setTimeout(() => router.push('/auth/login?verified=1'), 2000);
      })
      .catch((err) => {
        setStatus('error');
        setErrorMsg(err instanceof Error ? err.message : '인증에 실패했습니다.');
      });
  }, [token, router]);

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

  async function handleResend() {
    if (cooldown > 0 || !email) return;
    try {
      await resendVerification(email);
      setCooldown(60);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : '재발송에 실패했습니다.');
    }
  }

  const Logo = (
    <div className="flex items-center justify-center gap-2 mb-6">
      <svg width="24" height="24" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M16 2L28.124 9V23L16 30L3.876 23V9L16 2Z" fill="#1261c4"/>
        <path d="M16 5.5L25.5 10.75V21.25L16 26.5L6.5 21.25V10.75L16 5.5Z" fill="#ffffff" fillOpacity="0.15"/>
        <path d="M10 21V11h2.8l6.4 8V11H22v10h-2.8l-6.4-8v8H10Z" fill="#ffffff"/>
      </svg>
      <span className="text-[17px] font-bold text-[#1261c4] tracking-tight">NewsHive</span>
    </div>
  );

  // ── 토큰 자동 인증 중 ──────────────────────────────
  if (status === 'verifying') {
    return (
      <div className="min-h-[calc(100vh-48px)] flex items-center justify-center py-8">
        <div className="w-full max-w-sm bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center">
          {Logo}
          <div className="flex justify-center mb-4">
            <div className="w-10 h-10 border-4 border-[#1261c4] border-t-transparent rounded-full animate-spin" />
          </div>
          <p className="text-sm text-gray-500">이메일 인증을 처리하고 있습니다...</p>
        </div>
      </div>
    );
  }

  // ── 인증 성공 ──────────────────────────────────────
  if (status === 'success') {
    return (
      <div className="min-h-[calc(100vh-48px)] flex items-center justify-center py-8">
        <div className="w-full max-w-sm bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center">
          {Logo}
          <div className="w-14 h-14 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 mb-2">인증 완료!</h1>
          <p className="text-sm text-gray-500">이메일 인증이 완료되었습니다.<br />잠시 후 로그인 페이지로 이동합니다.</p>
        </div>
      </div>
    );
  }

  // ── 인증 실패 (토큰 만료 등) ──────────────────────
  if (status === 'error') {
    return (
      <div className="min-h-[calc(100vh-48px)] flex items-center justify-center py-8">
        <div className="w-full max-w-sm bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center">
          {Logo}
          <div className="w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 mb-2">인증 실패</h1>
          <p className="text-sm text-red-500 mb-4">{errorMsg}</p>
          <p className="text-sm text-gray-500 mb-4">
            링크가 만료되었다면 다시 회원가입해 주세요.
          </p>
          <Link href="/auth/register" className="inline-block py-2.5 px-6 bg-[#1261c4] hover:bg-[#0e52a8] text-white text-sm font-semibold rounded-lg transition">
            회원가입으로 돌아가기
          </Link>
        </div>
      </div>
    );
  }

  // ── 토큰 없음: 이메일 확인 대기 화면 ─────────────
  return (
    <div className="min-h-[calc(100vh-48px)] flex items-center justify-center py-8">
      <div className="w-full max-w-sm bg-white rounded-xl border border-gray-200 shadow-sm p-8">
        {Logo}

        <div className="flex justify-center mb-4">
          <div className="w-14 h-14 rounded-full bg-blue-50 flex items-center justify-center">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1261c4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
              <polyline points="22,6 12,13 2,6" />
            </svg>
          </div>
        </div>

        <h1 className="text-xl font-bold text-gray-900 text-center mb-2">이메일을 확인해 주세요</h1>
        <p className="text-sm text-gray-500 text-center mb-6">
          <span className="font-medium text-gray-700">{email || '입력하신 이메일'}</span>로<br />
          인증 링크를 발송했습니다.<br />
          메일의 <strong className="text-gray-700">이메일 인증하기</strong> 버튼을 클릭하면<br />
          가입이 완료됩니다.
        </p>

        {errorMsg && (
          <div className="mb-4 px-3 py-2.5 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {errorMsg}
          </div>
        )}

        {/* 재발송 버튼 */}
        <div className="text-center">
          <button
            type="button"
            onClick={handleResend}
            disabled={cooldown > 0 || !email}
            className="text-sm text-gray-500 hover:text-[#1261c4] disabled:text-gray-300 disabled:cursor-not-allowed transition"
          >
            {cooldown > 0 ? `재발송 (${cooldown}초 후 가능)` : '인증 링크 재발송'}
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
 * - ?token=xxx: 링크 클릭 자동 인증
 * - ?email=xxx: 이메일 확인 대기 화면
 */
export default function VerifyPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-[calc(100vh-48px)]"><span className="text-gray-400 text-sm">로딩 중...</span></div>}>
      <VerifyContent />
    </Suspense>
  );
}
