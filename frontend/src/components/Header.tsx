'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/components/AuthProvider';

const navItems = [
  { href: '/', label: '업종 현황' },
  { href: '/stocks', label: '종목' },
  { href: '/news', label: '뉴스' },
  { href: '/commodities', label: '원자재' },
  { href: '/disclosures', label: '공시' },
  { href: '/calendar', label: '캘린더' },
  { href: '/chat', label: 'AI 분석' },
];

export default function Header() {
  const pathname = usePathname();
  const { user, isLoggedIn, loading, logout } = useAuth();

  return (
    <header className="bg-white border-b border-gray-300">
      <div className="max-w-[1200px] mx-auto px-4">
        <div className="flex items-center h-12 gap-6">
          <Link href="/" className="flex items-center gap-1.5 text-[17px] font-bold text-[#1261c4] tracking-tight">
            <svg width="22" height="22" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M16 2L28.124 9V23L16 30L3.876 23V9L16 2Z" fill="#1261c4"/>
              <path d="M16 5.5L25.5 10.75V21.25L16 26.5L6.5 21.25V10.75L16 5.5Z" fill="#ffffff" fillOpacity="0.15"/>
              <path d="M10 21V11h2.8l6.4 8V11H22v10h-2.8l-6.4-8v8H10Z" fill="#ffffff"/>
            </svg>
            NewsHive
          </Link>

          {/* 네비게이션 메뉴 — 가능한 공간 모두 차지 */}
          <nav className="flex h-full flex-1">
            {navItems.map((item) => {
              const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center px-4 text-[13px] font-semibold border-b-2 transition-colors ${
                    isActive ? 'border-[#1261c4] text-[#1261c4]' : 'border-transparent text-[#666] hover:text-[#333]'
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {/* 사용자 인증 영역 — 로딩 중에는 아무것도 렌더링하지 않아 레이아웃 흔들림 방지 */}
          {!loading && (
            <div className="flex items-center gap-2 ml-auto shrink-0">
              {isLoggedIn ? (
                <>
                  <span className="text-[13px] text-gray-600 font-medium hidden sm:block">
                    {user?.name}
                  </span>
                  <button
                    type="button"
                    onClick={() => logout()}
                    className="px-3 py-1.5 text-[13px] font-semibold text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md transition hover:bg-gray-50"
                  >
                    로그아웃
                  </button>
                </>
              ) : (
                <Link
                  href="/auth/login"
                  className="px-3 py-1.5 text-[13px] font-semibold text-white bg-[#1261c4] hover:bg-[#0e52a8] rounded-md transition"
                >
                  로그인
                </Link>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
