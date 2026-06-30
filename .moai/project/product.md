# NewsHive — Product Overview

## Product Summary

NewsHive는 한국 주식시장(KOSPI/KOSDAQ) 급등주를 AI로 사전 탐지하여 자동 매매까지 수행하는 시스템이다. 뉴스·공시 크롤링 → 다중 탐지기 앙상블 → 일별 매수 시그널 생성 → 포지션 관리 → 성과 검증 → 자동 개선의 폐쇄 루프(Closed Loop)를 구성한다.

## Core User Problem

한국 주식 개인 투자자는 실시간 공시·테마 뉴스를 놓쳐 급등 초기 진입에 실패한다. NewsHive는 이 정보 격차를 AI 파이프라인으로 대체하여, 매일 장 마감 전(10:00 KST 신호 생성 → 11:00 매수 마감) 자동으로 최적 종목을 포지션에 편입한다.

## Key Features

### 1. 멀티소스 크롤링 (10분 주기)
- Naver News / Google News RSS / Yahoo Finance / 한국 금융 RSS
- DART(금융감독원) 공시 시스템 (30분 주기)
- AI 감성 분석 + 종목 매칭 + 중요도 분류 (breaking/important/routine)

### 2. 급등 탐지 앙상블 (10:00 KST)
8종 탐지기를 결합한 앙상블 (7종 활성, 1종 비활성):
- volume_news_combo (0.25): 거래량 이상 + 뉴스 콤보
- theme_cluster (0.19): 뉴스 토픽 클러스터링
- disclosure_pattern (0.14): 자사주 소각·공급계약·합병 등 공시 즉시 시그널
- momentum_continuation (0.12): 전일 상승 모멘텀 연속 패턴 (SPEC-AI-065)
- volume_breakout (0.11): 거래량 폭발 탐지 — Naver 3x+ (SPEC-AI-062)
- news_delayed (0.11): 뉴스 지연 반응 패턴 탐지 (SPEC-AI-039)
- weekend_gap_up (0.08): 주말·공휴일 갭상승 (SPEC-AI-050)
- legacy_detectors (0.00): 비활성 — group_cascade, forum_mention_surge 포함

### 3. 자동 매매 (Surge Portfolio)
- 초기 자본: 500만 KRW, 포지션당 14% (최대 7개 동시)
- 매수: 10:00~11:00 KST 시그널 기반 자동 집행
- 매도: 손절 -8%, 익절 +15%, 최대 보유 5거래일
- Preday 전략: 장 마감 후 공시 → 다음날 09:05 갭업 진입 (SPEC-AI-042)

### 4. 자동 개선 루프
- 18:30 KST: 당일 급등 결과 수집 + 시그널 정확도 검증
- 19:00 KST: 예측 실패 패턴 분석 + 파라미터 자동 조정
- 매주 일요일 22:00: AI 프롬프트 정제
- 매월 1일 23:00: 팩터 가중치 최적화

### 5. 매크로 리스크 감지
- 뉴스 기반 거시 경제 충격 탐지 (경고: 3건, 위기: 7건)
- 쿨다운 6시간, 집계 윈도우 1~6시간 설정 가능

### 6. 팔로잉 시스템 (SPEC-FOLLOW-001)
- 사용자 관심 종목 등록 + AI 키워드 자동 생성
- Telegram Bot 실시간 알림

## Deployment

- Backend: OCI Ubuntu VM (140.245.76.242:8000), FastAPI + systemd
- Frontend: Vercel 자동 배포 (main 브랜치)
- DB: PostgreSQL 16 (로컬 설치, Docker 없음)

## Business Metrics (Tracked)

- 시그널 정확도 (is_correct %), Recall, Precision
- Alpha vs KOSPI benchmark (alpha_pct)
- 포트폴리오 P&L (surge_portfolio 기준)
- 탐지기별 기여도 (contribution ratio)
