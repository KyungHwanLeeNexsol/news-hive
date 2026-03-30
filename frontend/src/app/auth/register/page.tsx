'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { registerUser } from '@/lib/api';

/**
 * 회원가입 페이지.
 * 성공 시 이메일 인증 페이지로 이동한다.
 */
export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError('');

    // 클라이언트 측 유효성 검사
    if (password.length < 8) {
      setError('비밀번호는 8자 이상이어야 합니다.');
      return;
    }
    if (password !== passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }

    setLoading(true);
    try {
      await registerUser({ email, password, name });
      // 인증 코드 입력 페이지로 이동 — email을 쿼리로 전달
      router.push(`/auth/verify?email=${encodeURIComponent(email)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '회원가입에 실패했습니다.');
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

        <h1 className="text-xl font-bold text-gray-900 text-center mb-6">회원가입</h1>

        {/* 에러 메시지 */}
        {error && (
          <div className="mb-4 px-3 py-2.5 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
              이름
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoComplete="name"
              placeholder="홍길동"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm outline-none focus:border-[#1261c4] focus:ring-1 focus:ring-[#1261c4] transition"
            />
          </div>

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
              autoComplete="new-password"
              placeholder="8자 이상"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm outline-none focus:border-[#1261c4] focus:ring-1 focus:ring-[#1261c4] transition"
            />
          </div>

          <div>
            <label htmlFor="passwordConfirm" className="block text-sm font-medium text-gray-700 mb-1">
              비밀번호 확인
            </label>
            <input
              id="passwordConfirm"
              type="password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="비밀번호 재입력"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm outline-none focus:border-[#1261c4] focus:ring-1 focus:ring-[#1261c4] transition"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-[#1261c4] hover:bg-[#0e52a8] text-white text-sm font-semibold rounded-lg transition disabled:opacity-60 disabled:cursor-not-allowed mt-2"
          >
            {loading ? '처리 중...' : '가입하기'}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-gray-500">
          이미 계정이 있으신가요?{' '}
          <Link href="/auth/login" className="text-[#1261c4] font-medium hover:underline">
            로그인
          </Link>
        </p>
      </div>
    </div>
  );
}
