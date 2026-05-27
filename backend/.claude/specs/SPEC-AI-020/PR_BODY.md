# SPEC-AI-020: 급등 시그널 PER/PBR 밸류에이션 필터 제거

## 요약

모멘텀 시그널에 가치 지표를 결합한 SPEC-AI-018 Phase 3 설계를 무효화하고, 필터 제거 시에도 시스템 동작을 보증하는 테스트로 전환한다.

## 배경

### 시간축 불일치 (Time-scale Mismatch)

급등 시그널은 뉴스, 거래량 급증, 공시 이벤트를 트리거로 하는 **24~72시간 단기 모멘텀** 신호. 반면 PER/PBR은 12개월 회계 데이터 기반 **장기 가치** 지표. 두 팩터는 시간 지평이 다르며, 학계 실증(Asness, Moskowitz & Pedersen 2013)에서 가치와 모멘텀 팩터는 종종 음의 상관을 보임. 모멘텀 전략에 가치 필터 결합 → alpha 희석.

### 한국 시장 산업 특성

한국 급등 후보는 코스닥 중소형 테마주(바이오·제약, 2차전지, AI) 다수:
- 적자 기업 비율 높음 → EPS < 0 → PER 정의 안 됨 또는 발산
- 성장 단계 기업 → 미래 현금흐름 시장 반영 → PBR 자연스럽게 높음 (과대평가 신호 아님)
- Tesla 2020년: PER > 1000, 최대 상승률 기록 → PER 필터 적용했다면 모든 매수 신호 차단

### 운영 데이터

SPEC-AI-019 필터 로직을 운영 `fund_signals` 96개 `signal_type='surge_candidate'`에 시뮬레이션:

**제외 종목 11개 (11.5%)**
| 분류 | 건수 | 대표 사례 |
|---|---|---|
| 바이오/제약 성장주 | 7 | 알테오젠(pbr=46.8), 펩트론(pbr=47.1), 보로노이(pbr=49.4), 에이비엘바이오(pbr=36.7), 디앤디파마텍(pbr=54.1), 네이처셀(pbr=32.7) |
| 적자 테마주(per>500) | 4 | 레인보우로보틱스(per=10027) 외 |
| 진짜 pump-and-dump 의심 | 0 | 해당 없음 |

**결론**: 의도(극단 과대평가 outlier 차단) vs 효과(성장주·바이오 부당 제외) 괴리 분명 → 필터 폐기.

## 변경 사항

### 제거 (REQ-AI020-001, REQ-AI020-006)

- **`fund_manager.py:1707-1724` valuation 필터 블록 제거**
  - SPEC-AI-018 Phase 3 `_gather_surge_candidates()` 에서 `per > 500 OR pbr > 30` 필터 로직 완전 제거
  - try/except 블록 구조 유지, 필터링 로직만 제거

- **SPEC-AI-018 REQ-006~008 deprecated 마킹**
  - `ValuationDisqualifiersConfig` docstring에 `[DEPRECATED]` 표시
  - `surge_detection.yaml` `valuation_disqualifiers:` 섹션을 주석(`# [DEPRECATED]`)으로 표시
  - Pydantic schema는 호환성 보존

### 추가 (REQ-AI020-002~004)

- **`SurgeCandidate.per`, `SurgeCandidate.pbr` 필드**
  - DB 컬럼 신규 추가 (Nullable, data-only)
  - 필터링 로직 없음 — 관찰성 및 사후 알파 분석용

- **`_extract_valuation(stock: Stock, ...)` 헬퍼**
  - 종목 fundamental 데이터에서 per/pbr 스냅샷 추출
  - 새로운 API 호출 없음 (piggy-back on existing queries)

- **3개 탐지기에서 per/pbr 수집**
  - `detect_theme_news_cluster()` → per/pbr 자동 채우기
  - `detect_volume_surge_news_combo()` → per/pbr 자동 채우기
  - `detect_disclosure_surge_pattern()` → per/pbr 자동 채우기

### Deprecated 보존 (REQ-AI020-005)

- **`ValuationDisqualifiersConfig` schema**
  - YAML 파싱 호환성 보존 (레거시 코드 호출 시에도 작동)
  - 모델 로드 후 사용하지 않음

- **`surge_detection.yaml` 섹션**
  ```yaml
  # [DEPRECATED as of SPEC-AI-020]
  # valuation_disqualifiers:
  #   max_per: 500
  #   max_pbr: 30
  #   skip_if_missing: true
  ```

### 테스트 (REQ-AI020-007~009)

- **Phase 3 테스트 retire**
  - `test_surge_ai018.py::TestPhase3ValuationDisqualifier` 4개 → `@pytest.mark.skip(reason="SPEC-AI-020: deprecated")`
  - 이유: 필터가 제거되었으므로 Phase 3 검증은 의미 없음
  - Schema 검증은 characterization test로 이관

- **신규 `test_surge_ai020_no_filter.py` 17개 케이스**
  - `test_surge_candidates_include_high_per_stocks()` — per > 500 종목도 시그널 풀 포함 확인
  - `test_surge_candidates_include_high_pbr_stocks()` — pbr > 30 종목도 시그널 풀 포함 확인
  - `test_detect_theme_cluster_per_pbr_snapshot()` — 탐지기가 per/pbr 정확히 스냅샷하는지 확인
  - `test_detect_volume_surge_per_pbr_snapshot()` — volume_surge 탐지기 per/pbr 수집 확인
  - `test_detect_disclosure_per_pbr_snapshot()` — disclosure 탐지기 per/pbr 수집 확인
  - 추가 12개: 엣지 케이스, 캐시 검증, 데이터 타입 보증

- **신규 `test_surge_ai020_characterization.py` 7개 케이스**
  - `test_biotec_growth_stocks_remain_in_signal_pool()` — 바이오 성장주 (e.g., 알테오젠) 매매 자격 유지
  - `test_highpbr_pharma_retained_as_signal()` — 제약사 고PBR 정상 포용
  - `test_deficit_companies_with_per_convergence()` — 적자 테마주 per 발산 조건에서도 신호 유지
  - `test_valuation_disqualifiers_config_deprecated()` — config 스키마 backward compat 확인
  - 추가 3개: 데이터 마이그레이션, 에러 처리, 시뮬레이션 재검증

### 코드 품질

- 기존 리팩토링 불필요 (필터 제거만 수행)
- MX 태그: `_extract_valuation()` 에 `@MX:NOTE(piggy-back observability)` 추가

## 테스트 결과

```
test_surge_ai020_no_filter.py::17 PASSED
test_surge_ai020_characterization.py::7 PASSED
test_surge_ai018.py::TestPhase3ValuationDisqualifier 4 SKIPPED (retired)

Totals:
  1096 passed (전체 급등 관련 테스트)
  4 skipped (Phase 3 retire)
  0 failed
  
Note: jose 모듈 사전 실패 제외 (unrelated to SPEC-AI-020)
```

## 영향 범위

### 매수 시그널 범위 확대

- 기존 11개 종목(바이오·성장주) 다시 포함
- 당일 시그널 풀: 평균 +11개 = ~107개 → 매수 후보 다양화

### 포트폴리오 산업 비중

- 모멘텀 시그널의 산업 다양성 회복
- 성장주·바이오 편향 제거 → KOSPI 전체 산업 커버리지 개선

### 성능 영향

- API 호출 변화 없음 (piggy-back 수집)
- DB 쿼리 변화 없음 (필터 제거만)
- 런타임 성능: 변화 없음

### 하위 호환성

- 기존 BriefingSignal / FundSignal 모델 호환
- valuation_disqualifiers YAML 로드해도 무시됨 (구현 미사용)
- API 응답 구조 변경 없음

## 관련 SPEC

- **SPEC-AI-018**: 급등 예측 신호 품질 개선 (Phase 3 도입 — 본 SPEC이 deprecate)
- **SPEC-AI-019**: 가치 필터 적용 범위 확장 (PR close without merge — 본 SPEC으로 superseded)

## Future Work

- **SPEC-AI-021 후보**: 모멘텀 친화 안전판 (관리종목·거래정지 차단, 변동성 캡, 유동성 필터)
- **SPEC-AI-022 후보**: per/pbr 데이터 활용 사후 알파 분석 (필터링 아닌 observability)

---

🗿 MoAI <email@mo.ai.kr>
