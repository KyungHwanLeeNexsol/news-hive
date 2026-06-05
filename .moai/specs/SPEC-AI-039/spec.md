# SPEC-AI-039: 급등 탐지 품질 개선 — Carry-Over 제한 + 뉴스 지연 반응 탐지기

**Status**: TODO  
**Created**: 2026-06-05  
**Priority**: P0 (오늘 운영 분석에서 도출된 즉각 개선 필요 항목)

---

## 배경 및 동기

2026-06-05 운영 분석에서 발견된 3가지 탐지 품질 문제:

1. **Carry-over 무제한 반복**: 6/1에 탐지된 시그널이 4영업일째 carry-over. 오늘 carry-over 종목 13개 중 11개 하락 (평균 -4%). 탐지 조건이 소멸한 종목을 계속 매수 후보로 유지하는 근본 결함.

2. **뉴스 지연 반응 미탐지**: 한올바이오파마(009420) 사례 — 6/3 "1조 로열티 기대감" 기사 후 6/5에 +6.5% 급등. 현재 탐지기는 당일~24시간 내 즉각 반응만 포착하며, 1-3일 후 반응하는 "뉴스 지연 효과" 패턴 미지원.

3. **고임팩트 바이오/기술이전 뉴스 저평가**: 기술이전, 임상성공, FDA 허가 등 폭발적 급등 트리거 키워드에 대한 특별 가중치 없음. 일반 뉴스와 동일하게 처리되어 중요 이벤트 신호가 묻힘.

---

## 요구사항

### REQ-039-001: Carry-Over 최대 거래일 제한

**When** surge_candidate 시그널의 carry-over 처리 시  
**The system shall** `originally_created_at` 기준으로 `max_carryover_days`(기본 3 거래일) 초과 시 해당 시그널을 carry-over 대상에서 제외한다  
**So that** 급등 조건이 소멸한 오래된 시그널이 매수 후보에 지속 잔류하지 않는다

구현 상세:
- `surge_detection.yaml`에 `carryover.max_trading_days: 3` 설정 추가
- 3 거래일 = 약 5 역일 (주말 1회 포함 계산): `originally_created_at < today - timedelta(days=5)` 시 skip
- 설정값 미존재 시 기본 5 역일 적용 (backward compatible)
- `_gather_surge_candidates` 내 carry-over 루프에서 체크

### REQ-039-002: 뉴스 지연 반응 탐지기

**When** `gather_surge_candidates` 실행 시  
**The system shall** `detect_news_delayed_response` 함수를 실행하여 최근 24-72시간 내 고임팩트 뉴스가 발생했으나 당일 가격 반응이 없는 종목을 탐지한다  
**So that** 뉴스 발생 1-3일 후 반응하는 "지연 급등" 패턴을 포착한다

구현 상세:
- `detect_news_delayed_response(db, config, market_regime)` → `list[SurgeCandidate]`
- 탐지 조건:
  1. 최근 24-72시간 내 고임팩트 뉴스 발생 (`HIGH_IMPACT_KEYWORDS` 매칭)
  2. 당일 24시간 이내 뉴스 없음 (당일 즉각 반응 이미 포착된 종목 제외)
  3. `news_delayed_score = keyword_weight × recency_factor` 산출
- 탐지기 가중치: `ensemble.weights`에 `news_delayed` 항목 추가 (0.15)
- 기존 가중치 재조정: `theme_cluster: 0.25`, `volume_news_combo: 0.32`, `disclosure_pattern: 0.18`, `legacy_detectors: 0.10`, `news_delayed: 0.15` (합계 1.0)

### REQ-039-003: 고임팩트 키워드 뉴스 가중치

**When** `detect_news_delayed_response` 또는 `detect_volume_surge_news_combo` 실행 시  
**The system shall** 아래 키워드 카테고리에 따라 뉴스 점수에 multiplier를 적용한다  
**So that** 일반 뉴스보다 급등 트리거 확률이 높은 이벤트를 차별화 탐지한다

고임팩트 키워드 및 가중치 (surge_detection.yaml에 설정):
```
high_impact_news:
  tech_transfer: ["기술이전", "로열티", "기술수출"]   # multiplier: 2.0
  clinical:      ["임상", "FDA", "허가", "승인"]        # multiplier: 1.8
  contract:      ["수주", "계약체결", "파트너십"]       # multiplier: 1.5
  default:       1.0
```

---

## 구현 파일

| 파일 | 변경 내용 |
|------|---------|
| `backend/app/surge_config/surge_detection.yaml` | carryover.max_trading_days, news_delayed 탐지기 가중치, high_impact_news 키워드 설정 추가 |
| `backend/app/surge_config/surge_settings.py` | CarryoverConfig, NewsDelayedConfig, HighImpactNewsConfig Pydantic 모델 추가 |
| `backend/app/services/surge_detector.py` | detect_news_delayed_response 함수 추가; gather_surge_candidates에 통합 |
| `backend/app/services/fund_manager.py` | _gather_surge_candidates carry-over 루프에 max_trading_days 체크 추가 |
| `backend/tests/test_surge_ai039.py` | 신규 인수 테스트 (REQ-039-001~003) |

---

## 수용 기준

- [ ] AC-039-001: carry-over 시 originally_created_at 기준 5 역일(≈3 거래일) 초과 시 해당 시그널 skip 처리
- [ ] AC-039-002: detect_news_delayed_response가 24-72h 고임팩트 뉴스 종목을 SurgeCandidate로 반환
- [ ] AC-039-003: 고임팩트 키워드 뉴스 포함 시 기본 대비 multiplier 적용된 score 산출
- [ ] AC-039-004: 앙상블 가중치 합산 = 1.0 (기존 validate_ensemble_weights 통과)
- [ ] AC-039-005: `uv run pytest tests/ --tb=short -q -m "not slow"` 전 패스

---

## 스코프 제외 (후속 SPEC)

- 우선주-본주 연동 탐지기 (SPEC-AI-040 예정)
- 뉴스 sentiment 모델 업그레이드
- 공시 기반 바이오 전용 탐지기

---

## 기술 접근법

### Carry-Over 제한 (REQ-039-001)

```python
# fund_manager.py _gather_surge_candidates carry-over 루프 내
max_days = getattr(surge_config, 'carryover', None)
max_days = max_days.max_trading_days if max_days else 3
cutoff = today_start - timedelta(days=int(max_days * 1.67))  # 3 거래일 ≈ 5 역일

for prev in prev_signals:
    # 오래된 carry-over 제외
    orig = prev.originally_created_at or prev.created_at
    if orig < cutoff:
        continue  # 3 거래일 초과 → skip
    ...
```

### 뉴스 지연 반응 탐지기 (REQ-039-002)

```
HIGH_IMPACT_KEYWORDS = {
    "tech_transfer": ["기술이전", "로열티", "기술수출"],      # 2.0x
    "clinical":      ["임상", "FDA", "허가", "승인"],        # 1.8x
    "contract":      ["수주", "계약체결", "파트너십"],        # 1.5x
}

탐지 알고리즘:
1. news_articles에서 24-72h 이내 published 기사 중 HIGH_IMPACT_KEYWORDS 매칭 기사 조회
2. 해당 기사와 연결된 stock 코드 추출 (news_stock_relations)
3. 당일(24h 이내) 동일 종목 기사 있으면 skip (이미 당일 반응 탐지기에서 처리)
4. keyword_category 기반 multiplier × recency_factor(72h→1.0, 48h→1.2, 24h→1.0) 적용
5. score = base_score × keyword_multiplier × recency_factor
6. score >= 0.25 이상인 종목을 SurgeCandidate로 반환 (news_delayed_score 필드)
```

### 앙상블 가중치 재조정 (REQ-039-002)

기존:
- theme_cluster: 0.28
- volume_news_combo: 0.35
- disclosure_pattern: 0.20
- legacy_detectors: 0.17

변경:
- theme_cluster: 0.25
- volume_news_combo: 0.32
- disclosure_pattern: 0.18
- legacy_detectors: 0.10
- news_delayed: 0.15

합계: 1.00 ✓

---

## 관련 SPEC

- SPEC-AI-029: 적응형 임계값 (win_rate 기반)
- SPEC-AI-030: volume_news_combo 추격매수 방지
- SPEC-AI-037: 테마 키워드 확장
- SPEC-AI-038: BEAR threshold cap, 장중 재탐지
