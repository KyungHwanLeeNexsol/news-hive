---
spec_id: SPEC-FOLLOW-001
type: acceptance
created: 2026-04-06
---

# SPEC-FOLLOW-001: 인수 기준 (Acceptance Criteria)

## 1. 종목 팔로잉 CRUD

### AC-001: 종목 팔로잉 등록 성공

```gherkin
Given 로그인한 사용자
And stocks 테이블에 종목코드 "298020" (효성티앤씨)이 존재
When POST /api/following/stocks {"stock_code": "298020"} 요청
Then 201 Created 응답
And stock_followings 테이블에 레코드 생성됨
And 응답에 following_id, stock_name, stock_code 포함
```

### AC-002: 중복 팔로잉 방지

```gherkin
Given 로그인한 사용자가 이미 "298020"을 팔로잉 중
When POST /api/following/stocks {"stock_code": "298020"} 요청
Then 409 Conflict 응답
And "이미 팔로잉 중인 종목입니다" 메시지 반환
```

### AC-003: 존재하지 않는 종목 팔로잉 시도

```gherkin
Given 로그인한 사용자
And stocks 테이블에 "999999" 종목코드가 존재하지 않음
When POST /api/following/stocks {"stock_code": "999999"} 요청
Then 404 Not Found 응답
And "종목을 찾을 수 없습니다" 메시지 반환
```

### AC-004: 팔로잉 해제 (CASCADE 삭제)

```gherkin
Given 로그인한 사용자가 "298020"을 팔로잉 중
And 해당 팔로잉에 키워드 5개가 등록되어 있음
When DELETE /api/following/stocks/298020 요청
Then 200 OK 응답
And stock_followings 레코드 삭제됨
And 연관된 stock_keywords 5개도 모두 삭제됨
```

### AC-005: 팔로잉 목록 조회

```gherkin
Given 로그인한 사용자가 3개 종목을 팔로잉 중
When GET /api/following/stocks 요청
Then 200 OK 응답
And 3개 종목 정보 반환 (stock_name, stock_code, keyword_count, last_notification_at)
And keyword_count는 각 종목의 키워드 수
```

## 2. AI 키워드 생성

### AC-010: AI 키워드 생성 성공

```gherkin
Given 로그인한 사용자가 "298020" (효성티앤씨)을 팔로잉 중
When POST /api/following/stocks/298020/keywords/ai-generate 요청
Then 200 OK 응답
And 4가지 카테고리(product, competitor, upstream, market) 키워드 반환
And 각 카테고리별 3~5개 키워드
And stock_keywords 테이블에 저장됨
And 각 키워드의 source="ai"
```

### AC-011: AI 생성 실패 시 graceful degradation

```gherkin
Given 로그인한 사용자가 "298020"을 팔로잉 중
And 모든 AI 프로바이더(Gemini + Z.AI)가 실패 상태
When POST /api/following/stocks/298020/keywords/ai-generate 요청
Then 200 OK 응답 (에러가 아님)
And 빈 키워드 목록 반환
And "AI 키워드 생성에 실패했습니다. 수동으로 키워드를 추가해 주세요." 메시지 포함
```

### AC-012: 중복 키워드 필터링

```gherkin
Given "298020" 팔로잉에 "스판덱스 가격" 키워드가 이미 존재
When AI 키워드 생성 결과에 "스판덱스 가격"이 포함됨
Then 해당 키워드는 건너뜀 (중복 생성하지 않음)
And 나머지 신규 키워드만 저장됨
```

### AC-013: AI 키워드 1일 1회 제한

```gherkin
Given "298020" 팔로잉에 대해 오늘 이미 AI 키워드를 생성함
When POST /api/following/stocks/298020/keywords/ai-generate 재요청
Then 429 Too Many Requests 응답
And "AI 키워드 생성은 하루 1회로 제한됩니다" 메시지 반환
```

## 3. 키워드 관리

### AC-020: 수동 키워드 추가

```gherkin
Given 로그인한 사용자가 "298020"을 팔로잉 중
When POST /api/following/stocks/298020/keywords {"keyword": "나일론 가격"} 요청
Then 201 Created 응답
And stock_keywords 테이블에 category="custom", source="manual"로 저장됨
```

### AC-021: 키워드 삭제

```gherkin
Given "298020" 팔로잉에 keyword_id=42인 키워드가 존재
When DELETE /api/following/stocks/298020/keywords/42 요청
Then 200 OK 응답
And 해당 키워드 삭제됨
```

### AC-022: 키워드 목록 카테고리별 그룹화

```gherkin
Given "298020" 팔로잉에 product 2개, competitor 1개, custom 3개 키워드 존재
When GET /api/following/stocks/298020/keywords 요청
Then 200 OK 응답
And 카테고리별로 그룹화된 키워드 목록 반환:
  product: [{id, keyword, source}, ...]
  competitor: [{id, keyword, source}, ...]
  custom: [{id, keyword, source}, ...]
```

## 4. 키워드 매칭 및 알림

### AC-030: 뉴스 키워드 매칭 알림 발송

```gherkin
Given 사용자 A가 "298020" 팔로잉에 "스판덱스 가격" 키워드 등록
And 사용자 A의 telegram_chat_id가 설정됨
When 뉴스 크롤러가 "효성티앤씨 스판덱스 가격 인상" 제목의 기사를 수집
And 키워드 매칭 스케줄러가 실행
Then 사용자 A의 텔레그램으로 알림 발송
And 알림 메시지: "[뉴스] 스판덱스 가격 관련\n{기사 제목}\n{기사 URL}"
And keyword_notifications 테이블에 기록 저장
```

### AC-031: 공시 키워드 매칭 알림 발송

```gherkin
Given 사용자 A가 "298020" 팔로잉에 "유상증자" 키워드 등록
When DART 크롤러가 효성티앤씨의 "유상증자 결정" 공시를 수집
And 키워드 매칭 스케줄러가 실행
Then 사용자 A의 텔레그램으로 알림 발송
And 알림 메시지: "[공시] 유상증자 관련\n{공시 제목}\n{DART URL}"
```

### AC-032: 중복 알림 방지

```gherkin
Given 사용자 A에게 뉴스 ID=100에 대한 알림이 이미 발송됨
And keyword_notifications에 (user_id=A, content_type="news", content_id=100) 레코드 존재
When 키워드 매칭 스케줄러가 다시 실행
Then 동일 콘텐츠에 대해 알림을 발송하지 않음
```

### AC-033: 텔레그램 미설정 시 Web Push 대체

```gherkin
Given 사용자 B의 telegram_chat_id가 NULL
And 사용자 B가 Web Push 구독 중
When 키워드 매칭이 발견됨
Then Web Push로 대체 알림 발송
And keyword_notifications.channel = "web_push"
```

### AC-034: 키워드 0개 종목은 매칭 제외

```gherkin
Given 사용자가 "005930"을 팔로잉하지만 키워드가 0개
When 키워드 매칭 스케줄러가 실행
Then "005930" 관련 매칭은 수행하지 않음
```

## 5. 텔레그램 연동

### AC-040: 텔레그램 연동 코드 생성

```gherkin
Given 로그인한 사용자
When POST /api/following/telegram/link 요청
Then 200 OK 응답
And 6자리 연동 코드 반환 (예: "A3F8K2")
And "텔레그램 봇(@NewsHiveBot)에 이 코드를 보내세요" 안내 메시지 포함
```

### AC-041: 텔레그램 봇에서 연동 코드 수신

```gherkin
Given 사용자에게 연동 코드 "A3F8K2"가 발급됨
When 사용자가 텔레그램 봇에 "A3F8K2" 메시지 전송
Then 봇이 webhook으로 메시지 수신
And users 테이블의 telegram_chat_id 업데이트
And 봇이 "연동 완료! 이제 키워드 알림을 받을 수 있습니다." 응답
```

### AC-042: 텔레그램 연동 상태 조회

```gherkin
Given 로그인한 사용자의 telegram_chat_id가 설정됨
When GET /api/following/telegram/status 요청
Then 200 OK 응답
And {"linked": true, "chat_id": "123456789"} 반환
```

### AC-043: 텔레그램 연동 해제

```gherkin
Given 로그인한 사용자의 telegram_chat_id가 설정됨
When DELETE /api/following/telegram/link 요청
Then 200 OK 응답
And users.telegram_chat_id를 NULL로 설정
```

## 6. 알림 히스토리

### AC-050: 알림 히스토리 조회

```gherkin
Given 사용자에게 10건의 알림이 발송됨
When GET /api/following/notifications?page=1&size=20 요청
Then 200 OK 응답
And 알림 목록 반환 (content_type, content_title, content_url, sent_at, channel)
And 최신 순 정렬
```

## Quality Gate

### 필수 통과 기준

- [ ] 모든 AC 시나리오 통과
- [ ] 단위 테스트 커버리지 85% 이상 (신규 파일 기준)
- [ ] ruff lint 경고 0건
- [ ] mypy/pyright 타입 에러 0건
- [ ] Alembic 마이그레이션 up/down 정상 동작
- [ ] 기존 테스트 regression 없음

### 성능 기준

- [ ] 키워드 매칭 작업: 1000개 뉴스 x 100개 키워드 기준 10초 이내
- [ ] API 응답 시간: 모든 엔드포인트 P95 < 500ms
- [ ] AI 키워드 생성: 30초 이내 (AI 응답 대기 포함)

### Definition of Done

- [ ] 백엔드 API 전체 구현 및 테스트 완료
- [ ] 프론트엔드 UI 구현 완료
- [ ] 텔레그램 봇 연동 동작 확인
- [ ] Alembic 마이그레이션 운영 DB 적용
- [ ] 배포 후 1종목 팔로잉 → 키워드 생성 → 알림 수신 e2e 테스트 통과
