"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";

export default function MaintenancePage(): React.ReactElement {
  const router = useRouter();
  const [countdown, setCountdown] = useState(10);
  const [checking, setChecking] = useState(false);

  const checkHealth = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      return res.ok;
    } catch {
      return false;
    }
  }, []);

  const retryNow = useCallback(async (): Promise<void> => {
    setChecking(true);
    const ok = await checkHealth();
    if (ok) {
      router.push("/");
    } else {
      setChecking(false);
      setCountdown(10);
    }
  }, [checkHealth, router]);

  // 10초마다 자동 재시도
  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          void retryNow();
          return 10;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [retryNow]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="text-center px-6">
        <div className="text-7xl mb-6 select-none">🔧</div>
        <h1 className="text-3xl font-bold text-white mb-3">시스템 점검 중</h1>
        <p className="text-gray-400 text-lg mb-2">
          서버 배포 또는 점검으로 잠시 이용이 제한됩니다.
        </p>
        <p className="text-gray-500 text-sm mb-8">
          보통 1~2분 내에 자동으로 복구됩니다.
        </p>

        <button
          onClick={() => void retryNow()}
          disabled={checking}
          className="px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 text-white rounded-lg font-medium transition-colors cursor-pointer disabled:cursor-not-allowed"
        >
          {checking ? "확인 중..." : `다시 시도 (${countdown}초 후 자동)`}
        </button>
      </div>
    </div>
  );
}
