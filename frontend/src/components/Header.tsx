"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/", label: "업종별 시세" },
  { href: "/news", label: "뉴스" },
  { href: "/manage", label: "관리" },
];

export default function Header() {
  const pathname = usePathname();

  return (
    <header className="bg-white border-b border-gray-300">
      <div className="max-w-[1200px] mx-auto px-4">
        <div className="flex items-center h-12 gap-6">
          <Link
            href="/"
            className="text-[17px] font-bold text-[#03c75a] tracking-tight"
          >
            증권 뉴스 트래커
          </Link>
          <nav className="flex h-full">
            {navItems.map((item) => {
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center px-4 text-[13px] font-semibold border-b-2 transition-colors ${
                    isActive
                      ? "border-[#03c75a] text-[#03c75a]"
                      : "border-transparent text-[#666] hover:text-[#333]"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </header>
  );
}
