'use client';

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { sendChatMessage } from '@/lib/api';
import type { ChatResponse } from '@/lib/types';
import { useAuth } from '@/components/AuthProvider';

// 채팅 메시지 인터페이스
interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  context_used?: string[];
  timestamp: string; // ISO 문자열로 저장/복원
  ai_model?: string | null;
}

// 멀티 세션 인터페이스
interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  backendSessionId?: string;
  createdAt: string;
  updatedAt: string;
}

// 간단한 마크다운 렌더링 (HTML 이스케이프 후 패턴 치환)
function renderMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(
      /```([\s\S]*?)```/g,
      '<pre class="bg-[#1e1e1e] text-[#d4d4d4] rounded-lg p-3 my-2 overflow-x-auto text-[13px] font-mono">$1</pre>',
    )
    .replace(
      /`([^`]+)`/g,
      '<code class="bg-[#f0f0f0] text-[#e12343] px-1.5 py-0.5 rounded text-[13px] font-mono">$1</code>',
    )
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br/>');
}

// 추천 질문 목록
const SUGGESTIONS = [
  '삼성전자 지금 사도 될까?',
  '반도체 섹터 최근 뉴스 요약해줘',
  '대창단조의 기술 지표 분석해줘',
  '오늘 시장 전체적인 분위기는 어때?',
] as const;

const MAX_SESSIONS = 50;

// 날짜 포맷: 오늘/어제/날짜
function formatSessionDate(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return '오늘';
  if (diffDays === 1) return '어제';
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

// 빈 세션 생성
function createEmptySession(): ChatSession {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    title: '새 대화',
    messages: [],
    backendSessionId: undefined,
    createdAt: now,
    updatedAt: now,
  };
}

export default function ChatPage() {
  // @MX:NOTE: 로그인 상태에 따라 사용자별 스토리지 키를 분리하여 세션 히스토리를 격리
  const { user } = useAuth();

  // 세션 목록 상태
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  // 현재 활성 세션 ID
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  // 사이드바 열림 상태 (모바일)
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // 호버 중인 세션 ID (삭제 버튼 표시용)
  const [hoveredSessionId, setHoveredSessionId] = useState<string>('');

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 스토리지 키 (user 변경 시 재계산)
  const storageKey = useMemo(
    () => (user ? `chat_sessions_${user.id}` : 'chat_sessions_guest'),
    [user],
  );

  // 현재 활성 세션 객체
  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) ?? null,
    [sessions, activeSessionId],
  );

  // 현재 메시지 목록 (timestamp를 Date로 변환해서 렌더링용)
  const messages = useMemo(
    () =>
      (activeSession?.messages ?? []).map((m) => ({
        ...m,
        timestamp: new Date(m.timestamp),
      })),
    [activeSession],
  );

  // 세션 목록 localStorage 저장
  const saveSessions = useCallback(
    (updated: ChatSession[]) => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(updated));
      } catch {
        // 저장 오류 무시
      }
    },
    [storageKey],
  );

  // user 변경 시 세션 목록 로드 + 레거시 마이그레이션
  useEffect(() => {
    setSessions([]);
    setActiveSessionId('');
    setInput('');

    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw) as ChatSession[];
        if (parsed.length > 0) {
          setSessions(parsed);
          setActiveSessionId(parsed[0].id);
          return;
        }
      }

      // 레거시 마이그레이션: 기존 단일 채팅 데이터 가져오기
      const legacyKey = user ? `chat_messages_${user.id}` : 'chat_messages_guest';
      const legacyRaw = localStorage.getItem(legacyKey);
      if (legacyRaw) {
        const legacyMessages = JSON.parse(legacyRaw) as Array<
          Omit<ChatMessage, 'timestamp'> & { timestamp: string }
        >;
        if (legacyMessages.length > 0) {
          const legacySessionKey = user ? `chat_session_id_${user.id}` : 'chat_session_id_guest';
          const legacySessionId = localStorage.getItem(legacySessionKey) ?? undefined;
          const now = new Date().toISOString();
          const firstUserMsg = legacyMessages.find((m) => m.role === 'user');
          const importedSession: ChatSession = {
            id: crypto.randomUUID(),
            title: firstUserMsg ? firstUserMsg.content.slice(0, 28) : '이전 대화',
            messages: legacyMessages.map((m) => ({ ...m, timestamp: m.timestamp })),
            backendSessionId: legacySessionId,
            createdAt: now,
            updatedAt: now,
          };
          setSessions([importedSession]);
          setActiveSessionId(importedSession.id);
          saveSessions([importedSession]);
          return;
        }
      }

      // 빈 상태: 새 세션 생성
      const newSession = createEmptySession();
      setSessions([newSession]);
      setActiveSessionId(newSession.id);
    } catch {
      // 파싱 오류 시 새 세션 생성
      const newSession = createEmptySession();
      setSessions([newSession]);
      setActiveSessionId(newSession.id);
    }
  }, [storageKey, user, saveSessions]);

  // 새 채팅 생성
  const handleNewChat = useCallback(() => {
    const newSession = createEmptySession();
    setSessions((prev) => {
      const updated = [newSession, ...prev].slice(0, MAX_SESSIONS);
      saveSessions(updated);
      return updated;
    });
    setActiveSessionId(newSession.id);
    setInput('');
    setSidebarOpen(false);
  }, [saveSessions]);

  // 세션 전환
  const handleSwitchSession = useCallback(
    (id: string) => {
      setActiveSessionId(id);
      setInput('');
      setSidebarOpen(false);
    },
    [],
  );

  // 세션 삭제
  const handleDeleteSession = useCallback(
    (id: string) => {
      setSessions((prev) => {
        const updated = prev.filter((s) => s.id !== id);
        // 삭제 후 남은 세션이 없으면 새 세션 생성
        if (updated.length === 0) {
          const newSession = createEmptySession();
          saveSessions([newSession]);
          setActiveSessionId(newSession.id);
          return [newSession];
        }
        saveSessions(updated);
        // 삭제된 세션이 활성이면 첫 번째 세션으로 전환
        setActiveSessionId((current) => {
          if (current === id) return updated[0].id;
          return current;
        });
        return updated;
      });
    },
    [saveSessions],
  );

  // 메시지 전송 후 세션 업데이트
  const updateSession = useCallback(
    (sessionId: string, updater: (session: ChatSession) => ChatSession) => {
      setSessions((prev) => {
        const updated = prev.map((s) => (s.id === sessionId ? updater(s) : s));
        saveSessions(updated);
        return updated;
      });
    },
    [saveSessions],
  );

  // 새 메시지 추가 시 자동 스크롤
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, loading]);

  // 메시지 전송
  const handleSend = useCallback(
    async (text?: string) => {
      const msg = (text ?? input).trim();
      if (!msg || loading) return;

      const currentSessionId = activeSessionId;
      const currentSession = sessions.find((s) => s.id === currentSessionId);
      if (!currentSession) return;

      const userMessage: ChatMessage = {
        role: 'user',
        content: msg,
        timestamp: new Date().toISOString(),
      };

      // 사용자 메시지 추가 + 타이틀 업데이트 (첫 메시지 기준)
      updateSession(currentSessionId, (s) => {
        const isFirst = s.messages.length === 0;
        return {
          ...s,
          title: isFirst ? msg.slice(0, 28) : s.title,
          messages: [...s.messages, userMessage],
          updatedAt: new Date().toISOString(),
        };
      });

      setInput('');
      setLoading(true);

      try {
        const history = currentSession.messages.map((m) => ({
          role: m.role,
          content: m.content,
        }));
        const res: ChatResponse = await sendChatMessage(
          msg,
          currentSession.backendSessionId,
          undefined,
          history,
        );

        const aiMessage: ChatMessage = {
          role: 'assistant',
          content: res.reply,
          context_used: res.context_used,
          timestamp: new Date().toISOString(),
          ai_model: res.ai_model,
        };

        updateSession(currentSessionId, (s) => ({
          ...s,
          backendSessionId: res.session_id,
          messages: [...s.messages, aiMessage],
          updatedAt: new Date().toISOString(),
        }));
      } catch {
        const errorMessage: ChatMessage = {
          role: 'assistant',
          content: '죄송합니다. 응답을 받는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.',
          timestamp: new Date().toISOString(),
        };
        updateSession(currentSessionId, (s) => ({
          ...s,
          messages: [...s.messages, errorMessage],
          updatedAt: new Date().toISOString(),
        }));
      } finally {
        setLoading(false);
      }
    },
    [input, loading, activeSessionId, sessions, updateSession],
  );

  // Enter 키로 전송 (Shift+Enter는 줄바꿈)
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  // 텍스트 영역 높이 자동 조절
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const textarea = e.target;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  }, []);

  return (
    // @MX:NOTE: position:fixed + top:48px로 layout main 패딩을 완전히 탈출하여 이중 스크롤바 방지
    <div
      className="flex overflow-hidden fixed bg-white"
      style={{ top: '48px', left: 0, right: 0, bottom: 0 }}
    >
      {/* 모바일 사이드바 오버레이 */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-10 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* 왼쪽 사이드바 */}
      <aside
        className={`
          flex flex-col w-[240px] flex-shrink-0
          bg-[#f8f9fa] border-r border-[#e5e5e5]
          transition-transform duration-200 ease-in-out
          md:relative md:translate-x-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
        `}
      >
        {/* 새 채팅 버튼 */}
        <div className="p-3 border-b border-[#e5e5e5]">
          <button
            onClick={handleNewChat}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-[#1261c4] text-[#1261c4] text-[13px] font-medium hover:bg-[#e8f0fe] transition-colors"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            새 채팅
          </button>
        </div>

        {/* 세션 목록 */}
        <div className="flex-1 overflow-y-auto py-1">
          {sessions.length === 0 || (sessions.length === 1 && sessions[0].messages.length === 0) ? (
            <div className="flex items-center justify-center h-20 text-[12px] text-[#bbb]">
              대화 내역이 없습니다
            </div>
          ) : (
            sessions.map((session) => {
              const isActive = session.id === activeSessionId;
              const isHovered = session.id === hoveredSessionId;
              return (
                <div
                  key={session.id}
                  className={`
                    relative flex items-center px-3 py-2.5 cursor-pointer
                    border-l-2 transition-colors
                    ${isActive
                      ? 'bg-[#e8f0fe] border-l-[#1261c4]'
                      : 'border-l-transparent hover:bg-[#f0f0f0]'
                    }
                  `}
                  onClick={() => handleSwitchSession(session.id)}
                  onMouseEnter={() => setHoveredSessionId(session.id)}
                  onMouseLeave={() => setHoveredSessionId('')}
                >
                  <div className="flex-1 min-w-0 pr-6">
                    <p
                      className={`text-[13px] font-medium truncate ${
                        isActive ? 'text-[#1261c4]' : 'text-[#333]'
                      }`}
                    >
                      {session.title}
                    </p>
                    <p className="text-[11px] text-[#aaa] mt-0.5">
                      {formatSessionDate(session.updatedAt)}
                    </p>
                  </div>
                  {/* 삭제 버튼 (호버 시 표시) */}
                  {isHovered && (
                    <button
                      className="absolute right-2 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded hover:bg-[#fde8ea] hover:text-[#e12343] text-[#bbb] transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteSession(session.id);
                      }}
                      title="대화 삭제"
                    >
                      <svg
                        width="13"
                        height="13"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                        <path d="M10 11v6" />
                        <path d="M14 11v6" />
                        <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
                      </svg>
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* 오른쪽 채팅 영역 */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* 모바일 전용 상단 바 (햄버거만 표시, 데스크탑은 숨김) */}
        <div className="flex md:hidden items-center px-4 py-2 border-b border-[#f0f0f0] bg-white">
          <button
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded hover:bg-[#f0f0f0] text-[#666]"
            onClick={() => setSidebarOpen(true)}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        </div>

        {/* 메시지 영역 */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-[800px] mx-auto px-4 py-6">
            {/* 빈 상태: 추천 질문 */}
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center min-h-[60vh]">
                <div className="w-14 h-14 rounded-2xl bg-[#1261c4] flex items-center justify-center mb-4">
                  <svg
                    width="28"
                    height="28"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="white"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                  </svg>
                </div>
                <h2 className="text-[18px] font-bold text-[#333] mb-1">AI 투자 분석 어시스턴트</h2>
                <p className="text-[13px] text-[#999] mb-6">
                  종목, 섹터, 시장에 대해 무엇이든 물어보세요
                </p>
                <div className="w-full max-w-[480px] space-y-2">
                  <p className="text-[12px] text-[#999] font-medium mb-2">이런 질문을 해보세요:</p>
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleSend(s)}
                      className="w-full text-left px-4 py-3 rounded-xl border border-[#e5e5e5] text-[13px] text-[#555] hover:border-[#1261c4] hover:text-[#1261c4] hover:bg-[#f7f8fa] transition-colors"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 메시지 목록 */}
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex mb-4 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div className="max-w-[85%]">
                  {/* 컨텍스트 태그 (AI 응답 위에 표시) */}
                  {msg.role === 'assistant' && (msg.context_used?.length || msg.ai_model) && (
                    <div className="flex flex-wrap items-center gap-1 mb-1.5">
                      {msg.context_used?.map((ctx, j) => (
                        <span
                          key={j}
                          className="inline-block px-2 py-0.5 bg-[#e8f0fe] text-[#1261c4] text-[11px] rounded-full font-medium"
                        >
                          {ctx}
                        </span>
                      ))}
                      {msg.ai_model && (() => {
                        const isGlm = msg.ai_model.toLowerCase().includes('glm');
                        return (
                          <span
                            className={`inline-block px-1.5 py-0.5 text-[10px] rounded font-mono border ${
                              isGlm
                                ? 'bg-[#fff8e1] text-[#f57f17] border-[#ffe082]'
                                : 'bg-[#e8f5e9] text-[#2e7d32] border-[#a5d6a7]'
                            }`}
                            title={isGlm ? 'Gemini rate limit 초과로 GLM 모델 사용 — 분석 품질이 다소 낮을 수 있습니다' : `AI 모델: ${msg.ai_model}`}
                          >
                            {msg.ai_model}
                          </span>
                        );
                      })()}
                    </div>
                  )}
                  <div
                    className={`px-4 py-3 rounded-2xl text-[14px] leading-relaxed ${
                      msg.role === 'user'
                        ? 'bg-[#1261c4] text-white rounded-br-md'
                        : 'bg-[#f2f3f5] text-[#333] rounded-bl-md'
                    }`}
                  >
                    {msg.role === 'assistant' ? (
                      <div
                        className="chat-markdown"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                      />
                    ) : (
                      <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
                    )}
                  </div>
                  <div
                    className={`text-[11px] text-[#bbb] mt-1 ${
                      msg.role === 'user' ? 'text-right' : 'text-left'
                    }`}
                  >
                    {msg.timestamp.toLocaleTimeString('ko-KR', {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </div>
                </div>
              </div>
            ))}

            {/* 로딩 인디케이터 */}
            {loading && (
              <div className="flex justify-start mb-4">
                <div className="bg-[#f2f3f5] px-4 py-3 rounded-2xl rounded-bl-md">
                  <div className="flex items-center gap-1.5">
                    <div
                      className="w-2 h-2 bg-[#999] rounded-full animate-bounce"
                      style={{ animationDelay: '0ms' }}
                    />
                    <div
                      className="w-2 h-2 bg-[#999] rounded-full animate-bounce"
                      style={{ animationDelay: '150ms' }}
                    />
                    <div
                      className="w-2 h-2 bg-[#999] rounded-full animate-bounce"
                      style={{ animationDelay: '300ms' }}
                    />
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* 입력 영역 */}
        <div className="border-t border-[#e5e5e5] bg-white">
          <div className="max-w-[800px] mx-auto px-4 py-3">
            <div className="flex items-end gap-2 bg-[#f7f8fa] rounded-2xl border border-[#e5e5e5] px-4 py-2 focus-within:border-[#1261c4] transition-colors">
              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder="메시지를 입력하세요..."
                rows={1}
                disabled={loading}
                className="flex-1 bg-transparent text-[14px] text-[#333] placeholder-[#aaa] resize-none outline-none min-h-[24px] max-h-[120px] py-1"
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-colors ${
                  input.trim() && !loading
                    ? 'bg-[#1261c4] text-white hover:bg-[#0d4ea0]'
                    : 'bg-[#e5e5e5] text-[#999]'
                }`}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
            <p className="text-[11px] text-[#bbb] text-center mt-2">
              AI 분석은 투자 참고용이며, 투자 판단의 책임은 본인에게 있습니다.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
