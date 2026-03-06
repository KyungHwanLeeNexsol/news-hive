'use client';

import { useEffect, useState } from 'react';
import { fetchEvents, createEvent, deleteEvent, seedEvents } from '@/lib/api';
import type { EconomicEvent } from '@/lib/types';

const CATEGORIES: Record<string, { label: string; color: string }> = {
  fomc: { label: 'FOMC', color: '#e12343' },
  options_expiry: { label: '옵션만기', color: '#f5a623' },
  economic_data: { label: '경제지표', color: '#1261c4' },
  geopolitical: { label: '지정학', color: '#8b5cf6' },
  earnings: { label: '실적발표', color: '#10b981' },
  custom: { label: '사용자', color: '#6b7280' },
};

const COUNTRIES: Record<string, string> = {
  KR: '🇰🇷',
  US: '🇺🇸',
  CN: '🇨🇳',
  JP: '🇯🇵',
  GLOBAL: '🌍',
};

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', weekday: 'short' });
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

function getDaysUntil(dateStr: string): number {
  const now = new Date();
  const d = new Date(dateStr);
  return Math.ceil((d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

function groupByMonth(events: EconomicEvent[]): Record<string, EconomicEvent[]> {
  const groups: Record<string, EconomicEvent[]> = {};
  for (const e of events) {
    const d = new Date(e.event_date);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    if (!groups[key]) groups[key] = [];
    groups[key].push(e);
  }
  return groups;
}

export default function CalendarPage() {
  const [events, setEvents] = useState<EconomicEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterCategory, setFilterCategory] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [seeding, setSeeding] = useState(false);

  // Add form state
  const [newTitle, setNewTitle] = useState('');
  const [newDate, setNewDate] = useState('');
  const [newCategory, setNewCategory] = useState('custom');
  const [newImportance, setNewImportance] = useState('medium');
  const [newCountry, setNewCountry] = useState('KR');

  function loadEvents() {
    setLoading(true);
    fetchEvents({ days: 90, past_days: 7, category: filterCategory })
      .then(setEvents)
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadEvents(); }, [filterCategory]);

  async function handleSeed() {
    setSeeding(true);
    try {
      const result = await seedEvents();
      if (result.seeded > 0) loadEvents();
    } catch { /* ignore */ }
    setSeeding(false);
  }

  async function handleAdd() {
    if (!newTitle.trim() || !newDate) return;
    try {
      await createEvent({
        title: newTitle.trim(),
        event_date: new Date(newDate).toISOString(),
        category: newCategory,
        importance: newImportance,
        country: newCountry,
      });
      setNewTitle('');
      setNewDate('');
      setShowAddForm(false);
      loadEvents();
    } catch { /* ignore */ }
  }

  async function handleDelete(id: number) {
    await deleteEvent(id);
    setEvents((prev) => prev.filter((e) => e.id !== id));
  }

  const grouped = groupByMonth(events);
  const monthKeys = Object.keys(grouped).sort();

  return (
    <div>
      <div className="section-box mb-3">
        <div className="section-title">
          <span>경제 이벤트 캘린더</span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleSeed}
              disabled={seeding}
              className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
            >
              {seeding ? '추가 중...' : '기본 일정 불러오기'}
            </button>
            <button
              onClick={() => setShowAddForm(!showAddForm)}
              className="text-[12px] font-medium text-white bg-[#1261c4] px-2.5 py-1 rounded hover:bg-[#0f4fa8]"
            >
              + 이벤트 추가
            </button>
          </div>
        </div>

        {/* Add form */}
        {showAddForm && (
          <div className="p-3 border-b border-[#e5e5e5] bg-[#f9fafb]">
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2">
              <input
                type="text"
                placeholder="이벤트 제목"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                className="border border-[#ddd] rounded px-2.5 py-1.5 text-[13px] focus:outline-none focus:border-[#1261c4]"
              />
              <input
                type="datetime-local"
                value={newDate}
                onChange={(e) => setNewDate(e.target.value)}
                className="border border-[#ddd] rounded px-2.5 py-1.5 text-[13px] focus:outline-none focus:border-[#1261c4]"
              />
              <div className="flex gap-1.5">
                <select
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  className="border border-[#ddd] rounded px-2 py-1.5 text-[13px] flex-1"
                >
                  {Object.entries(CATEGORIES).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </select>
                <select
                  value={newImportance}
                  onChange={(e) => setNewImportance(e.target.value)}
                  className="border border-[#ddd] rounded px-2 py-1.5 text-[13px] flex-1"
                >
                  <option value="low">낮음</option>
                  <option value="medium">보통</option>
                  <option value="high">높음</option>
                </select>
              </div>
              <div className="flex gap-1.5">
                <select
                  value={newCountry}
                  onChange={(e) => setNewCountry(e.target.value)}
                  className="border border-[#ddd] rounded px-2 py-1.5 text-[13px] flex-1"
                >
                  <option value="KR">한국</option>
                  <option value="US">미국</option>
                  <option value="CN">중국</option>
                  <option value="JP">일본</option>
                  <option value="GLOBAL">글로벌</option>
                </select>
                <button
                  onClick={handleAdd}
                  className="text-[13px] font-medium text-white bg-[#1261c4] px-3 py-1.5 rounded hover:bg-[#0f4fa8]"
                >
                  추가
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Category filter */}
        <div className="flex gap-1.5 p-3 border-b border-[#e5e5e5] flex-wrap">
          <button
            onClick={() => setFilterCategory('')}
            className={`px-2.5 py-1 rounded text-[12px] font-medium transition-colors ${
              !filterCategory ? 'bg-[#1261c4] text-white' : 'bg-[#f0f0f0] text-[#666] hover:bg-[#e5e5e5]'
            }`}
          >
            전체
          </button>
          {Object.entries(CATEGORIES).map(([key, { label, color }]) => (
            <button
              key={key}
              onClick={() => setFilterCategory(key)}
              className={`px-2.5 py-1 rounded text-[12px] font-medium transition-colors ${
                filterCategory === key ? 'text-white' : 'text-[#666] hover:bg-[#e5e5e5]'
              }`}
              style={filterCategory === key ? { backgroundColor: color } : { backgroundColor: '#f0f0f0' }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Event list grouped by month */}
        {loading ? (
          <div className="p-8 text-center text-[13px] text-[#999]">로딩 중...</div>
        ) : events.length === 0 ? (
          <div className="p-8 text-center text-[13px] text-[#999]">
            등록된 이벤트가 없습니다. &ldquo;기본 일정 불러오기&rdquo; 버튼을 눌러주세요.
          </div>
        ) : (
          <div>
            {monthKeys.map((monthKey) => {
              const monthEvents = grouped[monthKey];
              const [year, month] = monthKey.split('-');
              return (
                <div key={monthKey}>
                  <div className="px-3 py-2 bg-[#f5f6f8] text-[13px] font-bold text-[#333] border-b border-[#e5e5e5]">
                    {year}년 {parseInt(month)}월
                  </div>
                  {monthEvents.map((event) => {
                    const daysUntil = getDaysUntil(event.event_date);
                    const isPast = daysUntil < 0;
                    const isToday = daysUntil === 0;
                    const isSoon = daysUntil > 0 && daysUntil <= 3;
                    const cat = CATEGORIES[event.category] || CATEGORIES.custom;

                    return (
                      <div
                        key={event.id}
                        className={`flex items-center gap-3 px-3 py-2.5 border-b border-[#f0f0f0] hover:bg-[#f9fafb] ${
                          isPast ? 'opacity-50' : ''
                        }`}
                      >
                        {/* Date */}
                        <div className="w-[70px] shrink-0 text-center">
                          <div className="text-[13px] font-medium text-[#333]">
                            {formatDate(event.event_date)}
                          </div>
                          <div className="text-[11px] text-[#999]">
                            {formatTime(event.event_date)}
                          </div>
                        </div>

                        {/* Category badge */}
                        <span
                          className="shrink-0 px-1.5 py-0.5 rounded text-[11px] font-medium text-white"
                          style={{ backgroundColor: cat.color }}
                        >
                          {cat.label}
                        </span>

                        {/* Country */}
                        <span className="shrink-0 text-[14px]">{COUNTRIES[event.country] || ''}</span>

                        {/* Title + importance */}
                        <div className="flex-1 min-w-0">
                          <span className={`text-[13px] ${event.importance === 'high' ? 'font-bold text-[#333]' : 'text-[#555]'}`}>
                            {event.title}
                          </span>
                          {event.importance === 'high' && (
                            <span className="ml-1.5 text-[10px] text-[#e12343] font-bold">HIGH</span>
                          )}
                          {event.description && (
                            <p className="text-[11px] text-[#999] mt-0.5 truncate">{event.description}</p>
                          )}
                        </div>

                        {/* D-day */}
                        <div className="shrink-0 text-right w-[50px]">
                          {isToday ? (
                            <span className="text-[12px] font-bold text-[#e12343]">오늘</span>
                          ) : isSoon ? (
                            <span className="text-[12px] font-bold text-[#f5a623]">D-{daysUntil}</span>
                          ) : isPast ? (
                            <span className="text-[11px] text-[#999]">종료</span>
                          ) : (
                            <span className="text-[11px] text-[#999]">D-{daysUntil}</span>
                          )}
                        </div>

                        {/* Delete */}
                        <button
                          onClick={() => handleDelete(event.id)}
                          className="shrink-0 text-[14px] text-[#ccc] hover:text-[#e12343] transition-colors"
                          title="삭제"
                        >
                          &times;
                        </button>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
