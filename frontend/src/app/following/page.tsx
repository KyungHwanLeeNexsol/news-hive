'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useAuth } from '@/components/AuthProvider';
import { useRouter } from 'next/navigation';

// 팔로잉 종목 아이템 타입
interface FollowingItem {
  following_id: number;
  stock_code: string;
  stock_name: string;
  keyword_count: number;
  last_notification_at: string | null;
}

// 텔레그램 연동 상태 타입
interface TelegramStatus {
  linked: boolean;
  chat_id: string | null;
}

// 텔레그램 연동 코드 타입
interface TelegramLinkCode {
  code: string;
  instruction: string;
}

// 상대 시간 포맷 (마지막 알림 시간 표시용)
function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '없음';
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffMin < 1) return '방금 전';
  if (diffMin < 60) return `${diffMin}분 전`;
  if (diffHour < 24) return `${diffHour}시간 전`;
  if (diffDay < 7) return `${diffDay}일 전`;
  return date.toLocaleDateString('ko-KR');
}

export default function FollowingPage() {
  const { accessToken, isLoggedIn, loading: authLoading } = useAuth();
  const router = useRouter();

  // 팔로잉 목록 상태
  const [followingList, setFollowingList] = useState<FollowingItem[]>([]);
  const [listLoading, setListLoading] = useState(true);

  // 종목 추가 상태
  const [addCode, setAddCode] = useState('');
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState('');
  const [addSuccess, setAddSuccess] = useState('');

  // 삭제 확인 상태 (stock_code를 key로 사용)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // 텔레그램 상태
  const [telegramStatus, setTelegramStatus] = useState<TelegramStatus | null>(null);
  const [telegramLoading, setTelegramLoading] = useState(false);
  const [telegramLinkCode, setTelegramLinkCode] = useState<TelegramLinkCode | null>(null);
  const [telegramError, setTelegramError] = useState('');

  // 텔레그램 섹션 ref (스크롤 이동용)
  const telegramSectionRef = useRef<HTMLDivElement>(null);

  // 비로그인 시 로그인 페이지로 리디렉션
  useEffect(() => {
    if (!authLoading && !isLoggedIn) {
      router.push('/auth/login');
    }
  }, [authLoading, isLoggedIn, router]);

  // 팔로잉 목록 로드
  const loadFollowing = useCallback(async () => {
    if (!accessToken) return;
    setListLoading(true);
    try {
      const res = await fetch('/api/following/stocks', {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setFollowingList(data.items ?? []);
      }
    } catch {
      // 네트워크 오류 시 조용히 처리
    } finally {
      setListLoading(false);
    }
  }, [accessToken]);

  // 텔레그램 연동 상태 로드
  const loadTelegramStatus = useCallback(async () => {
    if (!accessToken) return;
    try {
      const res = await fetch('/api/following/telegram/status', {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setTelegramStatus(data);
      }
    } catch {
      // 텔레그램 상태 로드 실패 시 조용히 처리
    }
  }, [accessToken]);

  // 로그인 후 초기 데이터 로드
  useEffect(() => {
    if (accessToken) {
      loadFollowing();
      loadTelegramStatus();
    }
  }, [accessToken, loadFollowing, loadTelegramStatus]);

  // 종목 팔로잉 추가
  const handleAdd = async () => {
    const code = addCode.trim();
    if (!code) return;
    // 6자리 종목코드 검증
    if (!/^\d{6}$/.test(code)) {
      setAddError('종목코드는 6자리 숫자여야 합니다.');
      return;
    }
    if (!accessToken) return;

    setAddLoading(true);
    setAddError('');
    setAddSuccess('');

    try {
      const res = await fetch('/api/following/stocks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ stock_code: code }),
      });

      if (res.status === 201) {
        setAddSuccess(`${code} 종목을 팔로잉했습니다.`);
        setAddCode('');
        loadFollowing();
      } else if (res.status === 409) {
        setAddError('이미 팔로잉 중인 종목입니다.');
      } else if (res.status === 404) {
        setAddError('존재하지 않는 종목코드입니다.');
      } else {
        setAddError('종목 추가에 실패했습니다. 다시 시도해 주세요.');
      }
    } catch {
      setAddError('네트워크 오류가 발생했습니다.');
    } finally {
      setAddLoading(false);
    }
  };

  // 팔로잉 해제
  const handleUnfollow = async (stockCode: string) => {
    if (!accessToken) return;
    setDeleteLoading(true);
    try {
      const res = await fetch(`/api/following/stocks/${stockCode}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        setFollowingList((prev) => prev.filter((item) => item.stock_code !== stockCode));
      }
    } catch {
      // 삭제 실패 시 조용히 처리
    } finally {
      setDeleteLoading(false);
      setConfirmDelete(null);
    }
  };

  // 텔레그램 연동 코드 발급
  const handleTelegramLink = async () => {
    if (!accessToken) return;
    setTelegramLoading(true);
    setTelegramError('');
    setTelegramLinkCode(null);
    try {
      const res = await fetch('/api/following/telegram/link', {
        method: 'POST',
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setTelegramLinkCode(data);
      } else {
        setTelegramError('연동 코드 발급에 실패했습니다.');
      }
    } catch {
      setTelegramError('네트워크 오류가 발생했습니다.');
    } finally {
      setTelegramLoading(false);
    }
  };

  // 텔레그램 연동 해제
  const handleTelegramUnlink = async () => {
    if (!accessToken) return;
    setTelegramLoading(true);
    setTelegramError('');
    try {
      const res = await fetch('/api/following/telegram/link', {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        setTelegramStatus({ linked: false, chat_id: null });
        setTelegramLinkCode(null);
      } else {
        setTelegramError('연동 해제에 실패했습니다.');
      }
    } catch {
      setTelegramError('네트워크 오류가 발생했습니다.');
    } finally {
      setTelegramLoading(false);
    }
  };

  // 인증 로딩 중이거나 비로그인 상태면 렌더링 스킵
  if (authLoading || !isLoggedIn) {
    return null;
  }

  return (
    <div>
      {/* 팔로잉 목록 섹션 */}
      <div className="section-box mb-3">
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[#e5e5e5]">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold text-[#333]">
              <span className="text-[#1261c4] mr-1">★</span>팔로잉 종목
            </span>
            <span className="text-[12px] text-[#999]">{followingList.length}개</span>
          </div>
        </div>

        {/* 텔레그램 미연동 시 게이트 */}
        {telegramStatus !== null && !telegramStatus.linked ? (
          <div className="px-4 py-12 text-center">
            <p className="text-[14px] font-semibold text-[#333] mb-1">텔레그램 연동 후 이용 가능합니다</p>
            <p className="text-[12px] text-[#999] mb-4">
              팔로잉 알림은 텔레그램으로 전송됩니다. 먼저 아래에서 텔레그램 연동을 완료해 주세요.
            </p>
            <button
              type="button"
              onClick={() => telegramSectionRef.current?.scrollIntoView({ behavior: 'smooth' })}
              className="px-4 py-2 text-[13px] font-semibold bg-[#1261c4] text-white rounded hover:bg-[#0e4f9e] transition-colors"
            >
              텔레그램 연동하기 ↓
            </button>
          </div>
        ) : (
          <>
            {/* 종목 추가 입력 영역 */}
            <div className="px-4 py-3 border-b border-[#f0f0f0] bg-[#fafafa]">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={addCode}
                  onChange={(e) => {
                    setAddCode(e.target.value);
                    setAddError('');
                    setAddSuccess('');
                  }}
                  onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
                  placeholder="종목코드 6자리 입력 (예: 005930)"
                  maxLength={6}
                  className="flex-1 px-3 py-1.5 text-[13px] border border-[#ddd] rounded focus:outline-none focus:border-[#1261c4] bg-white"
                />
                <button
                  type="button"
                  onClick={handleAdd}
                  disabled={addLoading || !addCode.trim()}
                  className="px-4 py-1.5 text-[13px] font-semibold bg-[#1261c4] text-white rounded hover:bg-[#0e4f9e] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {addLoading ? '추가 중...' : '팔로잉 추가'}
                </button>
              </div>
              {/* 오류 / 성공 메시지 */}
              {addError && <p className="mt-1.5 text-[12px] text-[#e12343]">{addError}</p>}
              {addSuccess && <p className="mt-1.5 text-[12px] text-[#1261c4]">{addSuccess}</p>}
            </div>

            {/* 팔로잉 목록 */}
            {listLoading ? (
              // 스켈레톤 로딩
              <div className="divide-y divide-[#f0f0f0]">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={`sk-${i}`} className="px-4 py-3 flex items-center gap-3">
                    <div className="skeleton skeleton-text" style={{ width: '120px' }} />
                    <div className="skeleton skeleton-text-sm" style={{ width: '60px' }} />
                    <div className="ml-auto skeleton skeleton-text-sm" style={{ width: '80px' }} />
                  </div>
                ))}
              </div>
            ) : followingList.length === 0 ? (
              // 빈 상태
              <div className="px-4 py-16 text-center">
                <p className="text-[#999] text-[14px] mb-2">팔로잉 중인 종목이 없습니다. 종목을 추가해 보세요.</p>
                <p className="text-[#bbb] text-[12px]">위의 입력창에 종목코드를 입력하여 팔로잉을 시작하세요.</p>
              </div>
            ) : (
              // 팔로잉 카드 목록
              <div className="divide-y divide-[#f0f0f0]">
                {followingList.map((item) => (
                  <div key={item.following_id} className="px-4 py-3 flex items-center gap-3 hover:bg-[#f7f8fa]">
                    {/* 종목 정보 */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Link
                          href={`/following/${item.stock_code}`}
                          className="text-[14px] font-semibold text-[#333] hover:text-[#1261c4] hover:underline"
                        >
                          {item.stock_name}
                        </Link>
                        {/* 종목코드 배지 */}
                        <span className="text-[11px] px-1.5 py-0.5 rounded bg-[#e8f4fd] text-[#1261c4]">
                          {item.stock_code}
                        </span>
                        {/* 키워드 수 배지 */}
                        <span className="text-[11px] px-1.5 py-0.5 rounded bg-[#f5f5f5] text-[#666]">
                          키워드 {item.keyword_count}개
                        </span>
                      </div>
                      {/* 마지막 알림 시간 */}
                      <p className="text-[11px] text-[#999] mt-0.5">
                        마지막 알림: {formatRelativeTime(item.last_notification_at)}
                      </p>
                    </div>

                    {/* 키워드 관리 링크 */}
                    <Link
                      href={`/following/${item.stock_code}`}
                      className="px-3 py-1 text-[12px] font-medium rounded bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5] transition-colors shrink-0"
                    >
                      키워드 관리
                    </Link>

                    {/* 팔로잉 해제 버튼 */}
                    {confirmDelete === item.stock_code ? (
                      // 삭제 확인 UI
                      <div className="flex items-center gap-1 shrink-0">
                        <span className="text-[12px] text-[#666]">해제할까요?</span>
                        <button
                          type="button"
                          onClick={() => handleUnfollow(item.stock_code)}
                          disabled={deleteLoading}
                          className="px-2 py-1 text-[11px] font-semibold bg-[#e12343] text-white rounded hover:bg-[#c01030] disabled:opacity-50 transition-colors"
                        >
                          확인
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(null)}
                          className="px-2 py-1 text-[11px] font-medium bg-[#f5f5f5] text-[#666] rounded hover:bg-[#e5e5e5] transition-colors"
                        >
                          취소
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(item.stock_code)}
                        className="px-3 py-1 text-[12px] font-medium rounded border border-[#ddd] text-[#999] hover:border-[#e12343] hover:text-[#e12343] transition-colors shrink-0"
                      >
                        해제
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* 텔레그램 연동 섹션 */}
      <div ref={telegramSectionRef} className="section-box mb-3">
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[#e5e5e5]">
          <span className="text-[15px] font-semibold text-[#333]">텔레그램 알림 연동</span>
          {/* 연동 상태 배지 */}
          {telegramStatus && (
            <span className={`text-[11px] px-2 py-0.5 rounded font-medium ${
              telegramStatus.linked
                ? 'bg-[#e8f5e9] text-[#388e3c]'
                : 'bg-[#f5f5f5] text-[#999]'
            }`}>
              {telegramStatus.linked ? '연동됨' : '미연동'}
            </span>
          )}
        </div>

        <div className="px-4 py-4">
          {telegramStatus === null ? (
            // 텔레그램 상태 로딩 중
            <div className="skeleton skeleton-text" style={{ width: '200px' }} />
          ) : telegramStatus.linked ? (
            // 연동된 상태
            <div className="flex items-center gap-3">
              <div>
                <p className="text-[13px] text-[#333]">텔레그램이 연동되어 팔로잉 종목의 뉴스 알림을 받을 수 있습니다.</p>
                {telegramStatus.chat_id && (
                  <p className="text-[11px] text-[#999] mt-0.5">Chat ID: {telegramStatus.chat_id}</p>
                )}
              </div>
              <button
                type="button"
                onClick={handleTelegramUnlink}
                disabled={telegramLoading}
                className="ml-auto px-4 py-1.5 text-[13px] font-medium border border-[#ddd] text-[#666] rounded hover:border-[#e12343] hover:text-[#e12343] disabled:opacity-50 transition-colors shrink-0"
              >
                {telegramLoading ? '처리 중...' : '연동 해제'}
              </button>
            </div>
          ) : (
            // 미연동 상태
            <div>
              <p className="text-[13px] text-[#666] mb-3">
                텔레그램을 연동하면 팔로잉 종목의 키워드가 포함된 뉴스·공시를 실시간으로 받아볼 수 있습니다.
              </p>

              {/* 연동 코드 발급 후 안내 */}
              {telegramLinkCode ? (
                <div className="bg-[#f0f7ff] border border-[#1261c4] rounded p-4">
                  <p className="text-[13px] font-semibold text-[#1261c4] mb-3">연동 코드가 발급되었습니다</p>

                  {/* 코드 표시 */}
                  <div className="flex items-center gap-2 mb-4">
                    <code className="bg-white px-3 py-1.5 rounded border border-[#1261c4] text-[18px] font-bold text-[#1261c4] tracking-[0.2em]">
                      {telegramLinkCode.code}
                    </code>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(telegramLinkCode.code)}
                      className="px-3 py-1 text-[12px] text-[#666] bg-white border border-[#ddd] rounded hover:bg-[#f5f5f5] transition-colors"
                    >
                      복사
                    </button>
                  </div>

                  {/* 단계별 연동 가이드 */}
                  <div className="bg-white rounded border border-[#c5daf6] p-3">
                    <p className="text-[12px] font-semibold text-[#333] mb-2">연동 방법</p>
                    <ol className="space-y-2">
                      <li className="flex items-start gap-2">
                        <span className="shrink-0 w-4 h-4 rounded-full bg-[#1261c4] text-white text-[10px] font-bold flex items-center justify-center mt-0.5">1</span>
                        <span className="text-[12px] text-[#444]">
                          텔레그램 앱에서{' '}
                          <a
                            href="https://t.me/newshive_notify_bot"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[#1261c4] font-semibold underline"
                          >
                            @newshive_notify_bot
                          </a>
                          {' '}을 검색하거나 링크를 클릭하세요
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <span className="shrink-0 w-4 h-4 rounded-full bg-[#1261c4] text-white text-[10px] font-bold flex items-center justify-center mt-0.5">2</span>
                        <span className="text-[12px] text-[#444]">
                          봇 채팅창에{' '}
                          <strong className="text-[#1261c4]">{telegramLinkCode.code}</strong>
                          {' '}를 그대로 입력하고 전송하세요
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <span className="shrink-0 w-4 h-4 rounded-full bg-[#1261c4] text-white text-[10px] font-bold flex items-center justify-center mt-0.5">3</span>
                        <span className="text-[12px] text-[#444]">
                          봇에서 &quot;텔레그램 연동이 완료되었습니다&quot; 메시지가 오면 아래 버튼을 누르세요
                        </span>
                      </li>
                    </ol>
                    <button
                      type="button"
                      onClick={() => { loadTelegramStatus(); setTelegramLinkCode(null); }}
                      className="mt-3 w-full py-1.5 text-[12px] font-semibold bg-[#1261c4] text-white rounded hover:bg-[#0e4f9e] transition-colors"
                    >
                      연동 완료 확인
                    </button>
                    <p className="mt-2 text-[11px] text-[#999] text-center">⏱ 코드 유효시간: 10분 (만료 시 재발급 필요)</p>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={handleTelegramLink}
                  disabled={telegramLoading}
                  className="px-4 py-2 text-[13px] font-semibold bg-[#1261c4] text-white rounded hover:bg-[#0e4f9e] disabled:opacity-50 transition-colors"
                >
                  {telegramLoading ? '발급 중...' : '연동 코드 발급'}
                </button>
              )}

              {telegramError && (
                <p className="mt-2 text-[12px] text-[#e12343]">{telegramError}</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
