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
  timestamp: Date;
}

// 간단한 마크다운 렌더링 (볼드, 이탤릭, 코드, 줄바꿈)
function renderMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/```([\s\S]*?)```/g, '<pre class="bg-[#1e1e1e] text-[#d4d4d4] rounded-lg p-3 my-2 overflow-x-auto text-[13px] font-mono">$1</pre>')
    .replace(/`([^`]+)`/g, '<code class="bg-[#f0f0f0] text-[#e12343] px-1.5 py-0.5 rounded text-[13px] font-mono">$1</code>')
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
];

export default function ChatPage() {
  // @MX:NOTE: 로그인 상태에 따라 사용자별 스토리지 키를 분리하여 채팅 히스토리를 격리
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 로그인 사용자별 또는 게스트별 스토리지 키 (user 변경 시 재계산)
  const storageKeyMessages = useMemo(
    () => (user ? `chat_messages_${user.id}` : 'chat_messages_guest'),
    [user],
  );
  const storageKeySession = useMemo(
    () => (user ? `chat_session_id_${user.id}` : 'chat_session_id_guest'),
    [user],
  );

  // user가 변경될 때(로그인/로그아웃) 현재 메시지를 초기화하고 새 키로 복원
  useEffect(() => {
    setMessages([]);
    setSessionId(undefined);
    try {
      // 이전 버전 키(chat_messages, chat_session_id)에서 게스트 키로 1회 마이그레이션
      if (!user) {
        const legacyMessages = localStorage.getItem('chat_messages');
        const legacySession = localStorage.getItem('chat_session_id');
        if (legacyMessages && !localStorage.getItem(storageKeyMessages)) {
          localStorage.setItem(storageKeyMessages, legacyMessages);
        }
        if (legacySession && !localStorage.getItem(storageKeySession)) {
          localStorage.setItem(storageKeySession, legacySession);
        }
      }

      const savedMessages = localStorage.getItem(storageKeyMessages);
      const savedSession = localStorage.getItem(storageKeySession);
      if (savedMessages) {
        const parsed = JSON.parse(savedMessages) as Array<Omit<ChatMessage, 'timestamp'> & { timestamp: string }>;
        setMessages(parsed.map((m) => ({ ...m, timestamp: new Date(m.timestamp) })));
      }
      if (savedSession) setSessionId(savedSession);
    } catch {
      // 파싱 오류 무시
    }
  }, [storageKeyMessages, storageKeySession]);

  // 메시지 변경 시 현재 사용자 키로 localStorage 저장
  useEffect(() => {
    if (messages.length > 0) {
      localStorage.setItem(storageKeyMessages, JSON.stringify(messages));
    }
  }, [messages, storageKeyMessages]);

  // sessionId 변경 시 현재 사용자 키로 localStorage 저장
  useEffect(() => {
    if (sessionId) localStorage.setItem(storageKeySession, sessionId);
  }, [sessionId, storageKeySession]);

  // 대화 초기화
  const handleClear = useCallback(() => {
    setMessages([]);
    setSessionId(undefined);
    localStorage.removeItem(storageKeyMessages);
    localStorage.removeItem(storageKeySession);
  }, [storageKeyMessages, storageKeySession]);

  // 새 메시지 추가 시 자동 스크롤
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // 메시지 전송
  const handleSend = useCallback(async (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;

    // 사용자 메시지 추가
    const userMessage: ChatMessage = {
      role: 'user',
      content: msg,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }));
      const res: ChatResponse = await sendChatMessage(msg, sessionId, undefined, history);
      setSessionId(res.session_id);

      const aiMessage: ChatMessage = {
        role: 'assistant',
        content: res.reply,
        context_used: res.context_used,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, aiMessage]);
    } catch {
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: '죄송합니다. 응답을 받는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, sessionId]);

  // Enter 키로 전송 (Shift+Enter는 줄바꿈)
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  // 텍스트 영역 높이 자동 조절
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const textarea = e.target;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  }, []);

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 48px)' }}>
      {/* 상단 바 */}
      {messages.length > 0 && (
        <div className="flex justify-end px-4 py-2 border-b border-[#f0f0f0]">
          <button
            onClick={handleClear}
            className="text-[12px] text-[#999] hover:text-[#e12343] transition-colors"
          >
            대화 초기화
          </button>
        </div>
      )}
      {/* 채팅 영역 */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[800px] mx-auto px-4 py-6">
          {/* 빈 상태: 추천 질문 */}
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center min-h-[60vh]">
              <div className="w-14 h-14 rounded-2xl bg-[#1261c4] flex items-center justify-center mb-4">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
              <div className={`max-w-[85%] ${msg.role === 'user' ? 'order-1' : 'order-1'}`}>
                {/* 컨텍스트 태그 (AI 응답 위에 표시) */}
                {msg.role === 'assistant' && msg.context_used && msg.context_used.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1.5">
                    {msg.context_used.map((ctx, j) => (
                      <span
                        key={j}
                        className="inline-block px-2 py-0.5 bg-[#e8f0fe] text-[#1261c4] text-[11px] rounded-full font-medium"
                      >
                        {ctx}
                      </span>
                    ))}
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
                <div className={`text-[11px] text-[#bbb] mt-1 ${msg.role === 'user' ? 'text-right' : 'text-left'}`}>
                  {msg.timestamp.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            </div>
          ))}

          {/* 로딩 인디케이터 */}
          {loading && (
            <div className="flex justify-start mb-4">
              <div className="bg-[#f2f3f5] px-4 py-3 rounded-2xl rounded-bl-md">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 bg-[#999] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-2 h-2 bg-[#999] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-2 h-2 bg-[#999] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
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
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
  );
}
