'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useAuth } from '@/components/AuthProvider';
import { useRouter, useParams } from 'next/navigation';

// 카테고리 한글 레이블 매핑
const CATEGORY_LABELS: Record<string, string> = {
  product: '제품',
  competitor: '경쟁사',
  upstream: '전방산업',
  market: '시장',
  custom: '커스텀',
};

// 카테고리 표시 순서
const CATEGORY_ORDER = ['product', 'competitor', 'upstream', 'market', 'custom'] as const;
type Category = (typeof CATEGORY_ORDER)[number];

// 카테고리 뱃지 스타일
const CATEGORY_BADGE: Record<string, { bg: string; color: string }> = {
  product:    { bg: '#e8f0fc', color: '#1261c4' },
  competitor: { bg: '#fff3e0', color: '#e65100' },
  upstream:   { bg: '#e8f5e9', color: '#2e7d32' },
  market:     { bg: '#f0ebff', color: '#6c47c4' },
  custom:     { bg: '#f5f5f5', color: '#555' },
};

// 키워드 아이템 타입
interface KeywordItem {
  id: number;
  keyword: string;
  category: string;
  source: string;
  created_at: string;
}

// 키워드 목록 응답 타입 (카테고리별 분류)
type KeywordsResponse = Record<Category, KeywordItem[]>;

export default function StockKeywordPage() {
  const { accessToken, isLoggedIn, loading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  // @MX:NOTE: URL 파라미터에서 stock_code 추출 — Next.js dynamic route
  const stockCode = typeof params.stock_code === 'string' ? params.stock_code : '';

  // 키워드 목록 상태 (카테고리별)
  const [keywords, setKeywords] = useState<KeywordsResponse>({
    product: [],
    competitor: [],
    upstream: [],
    market: [],
    custom: [],
  });
  const [keywordsLoading, setKeywordsLoading] = useState(true);

  // AI 키워드 생성 상태
  const [aiLoading, setAiLoading] = useState(false);
  const [aiMessage, setAiMessage] = useState('');
  const [aiError, setAiError] = useState('');

  // 수동 키워드 추가 상태
  const [newKeyword, setNewKeyword] = useState('');
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState('');
  const [addSuccess, setAddSuccess] = useState('');

  // 삭제 중인 키워드 ID
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // 기업명 상태
  const [stockName, setStockName] = useState('');

  // 비로그인 시 로그인 페이지로 리디렉션
  useEffect(() => {
    if (!authLoading && !isLoggedIn) {
      router.push('/auth/login');
    }
  }, [authLoading, isLoggedIn, router]);

  // 키워드 목록 로드
  const loadKeywords = useCallback(async () => {
    if (!accessToken || !stockCode) return;
    setKeywordsLoading(true);
    try {
      const res = await fetch(`/api/following/stocks/${stockCode}/keywords`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data: KeywordsResponse = await res.json();
        setKeywords(data);
      }
    } catch {
      // 키워드 로드 실패 시 조용히 처리
    } finally {
      setKeywordsLoading(false);
    }
  }, [accessToken, stockCode]);

  // 로그인 후 초기 데이터 로드
  useEffect(() => {
    if (accessToken && stockCode) {
      loadKeywords();
    }
  }, [accessToken, stockCode, loadKeywords]);

  // 기업명 조회
  useEffect(() => {
    if (!stockCode) return;
    fetch(`/api/stocks?q=${encodeURIComponent(stockCode)}&limit=1`)
      .then((r) => r.json())
      .then((data: unknown) => {
        if (Array.isArray(data) && data.length > 0) {
          const item = data[0] as { name: string; stock_code: string };
          if (item.stock_code === stockCode) setStockName(item.name);
        }
      })
      .catch(() => {});
  }, [stockCode]);

  // AI 키워드 생성
  const handleAiGenerate = async () => {
    if (!accessToken || !stockCode) return;
    setAiLoading(true);
    setAiMessage('');
    setAiError('');
    try {
      const res = await fetch(`/api/following/stocks/${stockCode}/keywords/ai-generate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        // AI 생성 키워드 수 합산
        const totalCount = Object.values(data.keywords as Record<string, KeywordItem[]>)
          .reduce((sum, arr) => sum + arr.length, 0);
        setAiMessage(data.message || `${totalCount}개의 키워드가 생성되었습니다.`);
        // 목록 새로고침
        loadKeywords();
      } else if (res.status === 429 || res.status === 503) {
        setAiError('AI 서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.');
      } else {
        setAiError('AI 키워드 생성에 실패했습니다. 다시 시도해 주세요.');
      }
    } catch {
      setAiError('네트워크 오류가 발생했습니다.');
    } finally {
      setAiLoading(false);
    }
  };

  // 수동 키워드 추가
  const handleAddKeyword = async () => {
    const keyword = newKeyword.trim();
    if (!keyword || !accessToken || !stockCode) return;

    // 키워드 길이 검증 (2-100자)
    if (keyword.length < 2) {
      setAddError('키워드는 최소 2자 이상이어야 합니다.');
      return;
    }
    if (keyword.length > 100) {
      setAddError('키워드는 최대 100자까지 입력 가능합니다.');
      return;
    }

    setAddLoading(true);
    setAddError('');
    setAddSuccess('');

    try {
      const res = await fetch(`/api/following/stocks/${stockCode}/keywords`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ keyword }),
      });

      if (res.status === 201) {
        setAddSuccess(`"${keyword}" 키워드가 추가되었습니다.`);
        setNewKeyword('');
        loadKeywords();
      } else if (res.status === 409) {
        setAddError('이미 등록된 키워드입니다.');
      } else {
        setAddError('키워드 추가에 실패했습니다. 다시 시도해 주세요.');
      }
    } catch {
      setAddError('네트워크 오류가 발생했습니다.');
    } finally {
      setAddLoading(false);
    }
  };

  // 키워드 삭제
  const handleDeleteKeyword = async (keywordId: number) => {
    if (!accessToken || !stockCode) return;
    setDeletingId(keywordId);
    try {
      const res = await fetch(`/api/following/stocks/${stockCode}/keywords/${keywordId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        // 로컬 상태에서 즉시 제거 (재로드 없이)
        setKeywords((prev) => {
          const updated = { ...prev };
          for (const cat of CATEGORY_ORDER) {
            updated[cat] = updated[cat].filter((k) => k.id !== keywordId);
          }
          return updated;
        });
      }
    } catch {
      // 삭제 실패 시 조용히 처리
    } finally {
      setDeletingId(null);
    }
  };

  // 전체 키워드 (카테고리 순서대로 평탄화)
  const allKeywords = CATEGORY_ORDER.flatMap((cat) => keywords[cat] ?? []);

  // 전체 키워드 수 계산
  const totalKeywordCount = CATEGORY_ORDER.reduce(
    (sum, cat) => sum + (keywords[cat]?.length ?? 0),
    0
  );

  // 인증 로딩 중이거나 비로그인 상태면 렌더링 스킵
  if (authLoading || !isLoggedIn) {
    return null;
  }

  return (
    <div>
      {/* 페이지 헤더 */}
      <div className="section-box mb-3">
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[#e5e5e5]">
          <Link
            href="/following"
            className="text-[13px] text-[#666] hover:text-[#333] flex items-center gap-1"
          >
            ← 팔로잉 목록
          </Link>
          <span className="text-[#ddd]">|</span>
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold text-[#333]">
              {stockName || stockCode}
            </span>
            {stockName && (
              <span className="text-[12px] text-[#999]">{stockCode}</span>
            )}
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-[#f5f5f5] text-[#666]">
              키워드 {totalKeywordCount}개
            </span>
          </div>
        </div>

        {/* AI 키워드 생성 + 수동 키워드 추가 영역 */}
        <div className="px-4 py-3 border-b border-[#f0f0f0] bg-[#fafafa]">
          {/* AI 키워드 생성 */}
          <div className="flex items-center gap-3 mb-2.5">
            <button
              type="button"
              onClick={handleAiGenerate}
              disabled={aiLoading}
              className="px-4 py-1.5 text-[13px] font-semibold bg-[#6c47c4] text-white rounded hover:bg-[#5a3baa] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {aiLoading ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  AI 생성 중...
                </>
              ) : (
                'AI 키워드 생성'
              )}
            </button>
            {/* AI 생성 결과 메시지 */}
            {aiMessage && (
              <span className="text-[12px] text-[#388e3c]">{aiMessage}</span>
            )}
            {aiError && (
              <span className="text-[12px] text-[#e12343]">{aiError}</span>
            )}
          </div>

          {/* 수동 키워드 추가 */}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newKeyword}
              onChange={(e) => {
                setNewKeyword(e.target.value);
                setAddError('');
                setAddSuccess('');
              }}
              onKeyDown={(e) => e.key === 'Enter' && handleAddKeyword()}
              placeholder="키워드 직접 입력 (2-100자)"
              maxLength={100}
              className="flex-1 px-3 py-1.5 text-[13px] border border-[#ddd] rounded focus:outline-none focus:border-[#1261c4] bg-white"
            />
            <button
              type="button"
              onClick={handleAddKeyword}
              disabled={addLoading || !newKeyword.trim()}
              className="px-4 py-1.5 text-[13px] font-semibold bg-[#1261c4] text-white rounded hover:bg-[#0e4f9e] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {addLoading ? '추가 중...' : '추가'}
            </button>
          </div>
          {/* 수동 추가 결과 메시지 */}
          {addError && <p className="mt-1.5 text-[12px] text-[#e12343]">{addError}</p>}
          {addSuccess && <p className="mt-1.5 text-[12px] text-[#388e3c]">{addSuccess}</p>}
        </div>

        {/* 키워드 태그 목록 */}
        <div className="px-4 py-4 min-h-[120px]">
          {keywordsLoading ? (
            // 스켈레톤 로딩
            <div className="flex flex-wrap gap-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <div
                  key={`sk-${i}`}
                  className="skeleton"
                  style={{ width: `${60 + Math.random() * 40}px`, height: '28px', borderRadius: '14px' }}
                />
              ))}
            </div>
          ) : allKeywords.length === 0 ? (
            // 빈 상태
            <div className="text-center py-8">
              <p className="text-[#999] text-[13px]">등록된 키워드가 없습니다.</p>
              <p className="text-[#bbb] text-[12px] mt-1">
                위의 입력창에서 키워드를 추가하거나 AI 키워드 생성을 사용해 보세요.
              </p>
            </div>
          ) : (
            // 키워드 태그 목록
            <div className="flex flex-wrap gap-2">
              {allKeywords.map((item) => {
                const badge = CATEGORY_BADGE[item.category] ?? CATEGORY_BADGE.custom;
                return (
                  <span
                    key={item.id}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#f0f4ff] border border-[#c5d7f7] rounded-full text-[13px] text-[#1261c4]"
                  >
                    {item.keyword}
                    {/* 카테고리 뱃지 */}
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                      style={{ backgroundColor: badge.bg, color: badge.color }}
                    >
                      {CATEGORY_LABELS[item.category] ?? item.category}
                    </span>
                    {/* AI 생성 키워드 뱃지 */}
                    {item.source === 'ai' && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#6c47c4] text-white font-bold tracking-wide">
                        AI
                      </span>
                    )}
                    {/* 키워드 삭제 버튼 */}
                    <button
                      type="button"
                      onClick={() => handleDeleteKeyword(item.id)}
                      disabled={deletingId === item.id}
                      className="ml-0.5 text-[#999] hover:text-[#e12343] transition-colors disabled:opacity-50"
                      aria-label={`${item.keyword} 키워드 삭제`}
                    >
                      {deletingId === item.id ? (
                        <span className="inline-block w-3 h-3 border border-[#999] border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <path d="M1 1L11 11M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                        </svg>
                      )}
                    </button>
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
