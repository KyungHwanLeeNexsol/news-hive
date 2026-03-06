"""2026년 주요 경제 이벤트 시드 데이터."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.economic_event import EconomicEvent

# 2026년 주요 경제 이벤트
DEFAULT_EVENTS = [
    # FOMC 회의 (2026년 예정)
    {"title": "FOMC 회의 (1월)", "event_date": "2026-01-28T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},
    {"title": "FOMC 회의 (3월)", "event_date": "2026-03-18T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},
    {"title": "FOMC 회의 (5월)", "event_date": "2026-05-06T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},
    {"title": "FOMC 회의 (6월)", "event_date": "2026-06-17T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},
    {"title": "FOMC 회의 (7월)", "event_date": "2026-07-29T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},
    {"title": "FOMC 회의 (9월)", "event_date": "2026-09-16T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},
    {"title": "FOMC 회의 (11월)", "event_date": "2026-11-04T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},
    {"title": "FOMC 회의 (12월)", "event_date": "2026-12-16T19:00:00Z", "category": "fomc", "importance": "high", "country": "US"},

    # 한국 금통위
    {"title": "한국은행 금통위 (1월)", "event_date": "2026-01-16T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},
    {"title": "한국은행 금통위 (2월)", "event_date": "2026-02-27T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},
    {"title": "한국은행 금통위 (4월)", "event_date": "2026-04-09T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},
    {"title": "한국은행 금통위 (5월)", "event_date": "2026-05-28T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},
    {"title": "한국은행 금통위 (7월)", "event_date": "2026-07-09T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},
    {"title": "한국은행 금통위 (8월)", "event_date": "2026-08-27T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},
    {"title": "한국은행 금통위 (10월)", "event_date": "2026-10-15T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},
    {"title": "한국은행 금통위 (11월)", "event_date": "2026-11-26T01:00:00Z", "category": "economic_data", "importance": "high", "country": "KR"},

    # 옵션 만기일 (매월 둘째 목요일)
    {"title": "옵션 만기일 (3월)", "event_date": "2026-03-12T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "옵션 만기일 (4월)", "event_date": "2026-04-09T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "옵션 만기일 (5월)", "event_date": "2026-05-14T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "쿼드러플 위칭데이 (6월)", "event_date": "2026-06-11T00:00:00Z", "category": "options_expiry", "importance": "high", "country": "KR"},
    {"title": "옵션 만기일 (7월)", "event_date": "2026-07-09T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "옵션 만기일 (8월)", "event_date": "2026-08-13T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "옵션 만기일 (9월)", "event_date": "2026-09-10T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "옵션 만기일 (10월)", "event_date": "2026-10-08T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "옵션 만기일 (11월)", "event_date": "2026-11-12T00:00:00Z", "category": "options_expiry", "importance": "medium", "country": "KR"},
    {"title": "쿼드러플 위칭데이 (12월)", "event_date": "2026-12-10T00:00:00Z", "category": "options_expiry", "importance": "high", "country": "KR"},

    # 주요 경제지표 발표
    {"title": "미국 CPI 발표 (3월)", "event_date": "2026-03-11T13:30:00Z", "category": "economic_data", "importance": "high", "country": "US"},
    {"title": "미국 CPI 발표 (4월)", "event_date": "2026-04-14T13:30:00Z", "category": "economic_data", "importance": "high", "country": "US"},
    {"title": "미국 고용보고서 (3월)", "event_date": "2026-03-06T14:30:00Z", "category": "economic_data", "importance": "high", "country": "US"},
    {"title": "미국 고용보고서 (4월)", "event_date": "2026-04-03T13:30:00Z", "category": "economic_data", "importance": "high", "country": "US"},
]


def seed_economic_events(db: Session) -> int:
    """시드 이벤트 추가 (이미 존재하는 제목은 스킵)."""
    existing_titles = {e.title for e in db.query(EconomicEvent.title).all()}

    count = 0
    for evt in DEFAULT_EVENTS:
        if evt["title"] in existing_titles:
            continue
        event = EconomicEvent(
            title=evt["title"],
            event_date=datetime.fromisoformat(evt["event_date"]),
            category=evt["category"],
            importance=evt["importance"],
            country=evt["country"],
        )
        db.add(event)
        existing_titles.add(evt["title"])
        count += 1

    if count:
        db.commit()
    return count
