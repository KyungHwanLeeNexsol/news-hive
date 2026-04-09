# SPEC-KS200-001: KOSPI 200 스토캐스틱+이격도 자동매매 시스템

## 상태
- Status: approved
- Created: 2026-04-08
- Author: Nexsol

## 개요

KOSPI 200 구성종목을 대상으로 스토캐스틱 슬로우(Stochastics Slow)와 이격도(Disparity Ratio)를 결합한 자동매매 전략을 구현한다.
기존 AI 펀드 페이퍼 트레이딩(virtual_portfolios), VIP 추종 매매(vip_portfolios)와 완전히 독립된 3번째 매매 모델이다.

## 유니버스

- KOSPI 200 구성종목 (KRX 데이터포털 API 기준)
- 제외 조건: 거래정지, 단기과열, 투자경고/위험 종목

## 자본금

- 초기 자본금: 100,000,000 KRW (1억원)
- 종목당 최대 투자금액: 10,000,000 KRW (초기자본의 10%)
- 최대 동시 보유 종목 수: 10개

## 기술적 지표

### 스토캐스틱 슬로우 (sto1=12, sto2=5, sto3=5)

- %K_raw[i] = (Close[i] - min(Low[i-11..i])) / (max(High[i-11..i]) - min(Low[i-11..i])) * 100
  - max == min 경우: %K_raw = 50.0 (엣지케이스 처리)
- %K_slow[i] = SMA(%K_raw, 5) — 슬로잉 %K
- %D[i] = SMA(%K_slow, 5) — 시그널 라인
- 하한 밴드: 20, 상한 밴드: 80

### 이격도 (period3=20)

- MA20[i] = SMA(Close, 20)
- Disparity[i] = (Close[i] / MA20[i]) * 100
- 하한 밴드: 97.0, 상한 밴드: 103.0

## 매수 신호 (모든 조건 동시 충족)

1. prev_stoch_k < 20 AND curr_stoch_k >= 20 (하한 밴드 상향 돌파)
2. prev_disparity < 97 AND curr_disparity >= 97 (하한 밴드 상향 돌파)

## 매도 신호 (모든 조건 동시 충족)

1. prev_stoch_k > 80 AND curr_stoch_k <= 80 (상한 밴드 하향 돌파)
2. prev_disparity > 103 AND curr_disparity <= 103 (상한 밴드 하향 돌파)

## 매매 실행

- 매수: fetch_current_price()로 현재가 조회 후 10,000,000원 한도 내 최대 수량 매수
- 매도: 보유 수량 100% 청산
- 스케줄: 매일 15:30 KST (장 마감 후) 평일 실행
- 손절/익절 없음 — 매도 신호 또는 수동 청산만

## 데이터 요구사항

- fetch_stock_price_history(stock_code, pages=3): 최신순 ~30거래일 데이터
- 최소 필요 봉 수: STO1(12) + STO2(5) - 1 = 16봉 (%K_slow 계산), +1(prev) = 17봉

## DB 테이블

- ks200_portfolios: 포트폴리오 (단일 인스턴스)
- ks200_trades: 매매 기록
- ks200_signals: 신호 기록 (미실행 포함)

## API 엔드포인트 (prefix: /api/ks200-trading)

- GET /portfolio — 포트폴리오 현황
- GET /positions — 오픈 포지션 목록
- GET /trades — 거래 이력
- GET /signals — 최근 신호 목록
- POST /trigger-scan — 수동 신호 스캔 및 실행 (관리자 전용)
