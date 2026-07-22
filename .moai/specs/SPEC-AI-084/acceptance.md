# SPEC-AI-084 — Acceptance Criteria (인수 기준)

> 각 AC의 **통과 기준은 볼드 처리된 EARS(Easy Approach to Requirements Syntax) 정규 문장**
> (Ubiquitous / Event-Driven / State-Driven / Unwanted / Optional)이다. 각 EARS 문장은 트리거 키워드
> 정확히 1개(**WHEN** / **WHILE** / **IF** / **WHERE** — Ubiquitous는 트리거 없음)와 SHALL/SHALL NOT
> 절 정확히 1개만 포함한다. 하나의 AC가 긍정·부정 거동을 모두 검증하는 경우 각각을 **별도의 EARS
> 문장**으로 분리한다(복합 2-절 문장·em-dash 결합 2차 정규 절·볼드 SHALL과 비형식 모달 혼용 금지 —
> SPEC-AI-081-review-3.md D1/D2 교훈).
> 각 EARS 문장 아래 _재현 시나리오(비규범)_ 로 표기된 Given-When-Then 블록은 그 기준을 예시하는
> 비규범(non-normative) 서술이며 그 자체가 통과 조건은 아니다. 각 AC는 spec.md의 REQ-AI084-0NN에
> 매핑된다. 운영 모드는 예측 기록(SPEC-AI-043)이며 실매매 미검증.

## 그룹 C — 키워드 태깅 인프라

### AC-084-001 (REQ-AI084-001) — 뉴스/공시 기반 키워드 추출

- **WHEN** 추적 종목(`stocks`)에 연결된 뉴스(`NewsStockRelation` 조인)·공시 텍스트에 대해 키워드
  태깅이 수행되면, the system **SHALL** 그 종목의 `stocks.keywords`(추출 전 NULL)를 추출된 테마
  키워드로 채워 비어있지 않은 배열로 만들어야 한다.

_재현 시나리오(비규범):_
- **Given** 로봇 관련 뉴스가 연결된 종목(예: 레인보우로보틱스, NewsStockRelation 존재)
- **When** 키워드 태깅이 수행되면
- **Then** 그 종목의 `stocks.keywords`에 테마 키워드(예: "로봇")가 채워진다(추출 전 NULL → 추출 후 비어있지 않음).

### AC-084-002 (REQ-AI084-002) — 배치 백필 유계·멱등

- **WHEN** 배치 백필이 1회 실행된 뒤 동일 유니버스에 대해 재실행되면, the system **SHALL** 1차 실행에서 채운 키워드를 파괴하지 않고 보존해야 한다(멱등).
- **WHILE** 배치 백필이 실행되는 동안, the system **SHALL** 유니버스 크기에 비례한 유계(bounded) 비용 내에서 수행되어야 한다(무유계 확장 금지).

_재현 시나리오(비규범):_
- **Given** `stocks.keywords`가 전면 NULL인 기존 유니버스
- **When** 배치 백필을 실행하고, 이어서 한 번 더 실행하면
- **Then** 1차 실행으로 다수 종목의 keywords가 채워지고, 2차 실행이 이미 채운 키워드를 파괴하지 않는다(멱등). 비용은 유니버스 크기에 비례한 유계 범위 내.

### AC-084-003 (REQ-AI084-004) — 수동/사용자 키워드 오염 금지 [HARD]

- **WHILE** 배치/지속 태깅이 실행되는 동안, the system **SHALL NOT** 수동 설정된 `stocks.keywords`를 무단으로 덮어써서는 안 된다.
- **WHILE** 배치/지속 태깅이 실행되는 동안, the system **SHALL NOT** following 시스템의 사용자 키워드 데이터(`keyword_matcher`/`following`)를 변경해서는 안 된다.

_재현 시나리오(비규범):_
- **Given** 수동 설정된 `stocks.keywords`를 가진 종목 + following 시스템 사용자 키워드 데이터
- **When** 배치/지속 태깅이 실행되면
- **Then** 수동 종목 키워드가 무단 덮어써지지 않고, `keyword_matcher`/`following` 사용자 키워드 데이터는 전혀 변경되지 않는다.

### AC-084-004 (REQ-AI084-004) — LLM 예산 가드

- **IF** 키워드 추출이 LLM 경로를 포함하는 구성에서 배치 백필이 실행되면, **THEN** the system **SHALL** 무료 티어·규칙/사전 추출을 우선하고 예산 상한 도달 시 규칙 폴백으로 전환해야 한다.
- **IF** 키워드 추출이 LLM 경로를 포함하는 구성에서 배치 백필이 실행되면, **THEN** the system **SHALL NOT** 무유계 LLM 호출로 예산을 폭발시켜서는 안 된다.

_재현 시나리오(비규범):_
- **Given** 키워드 추출이 LLM 경로를 포함하는 구성
- **When** 배치 백필이 실행되면
- **Then** 무료 티어 우선 + 규칙/사전 추출 우선이 적용되고, 무유계 LLM 호출로 예산을 폭발시키지 않는다(예산 상한 도달 시 규칙 폴백).

### AC-084-005 (REQ-AI084-003) — 지속 태깅 신선도 + 캡

- **WHILE** 신규 뉴스/공시가 유입된 종목에 대해 지속 태깅 파이프라인이 실행되는 동안, the system **SHALL** 그 종목의 `stocks.keywords`를 갱신해 신선하게 유지해야 한다.
- **WHILE** 지속 태깅이 실행되는 동안, the system **SHALL NOT** 종목당 키워드 수가 설정 상한을 초과하도록 증식시켜서는 안 된다(무한 증식 방지).

_재현 시나리오(비규범):_
- **Given** 신규 뉴스/공시가 유입된 종목
- **When** 지속 태깅 파이프라인이 실행되면
- **Then** 해당 종목 keywords가 갱신되며, 종목당 키워드 수가 설정 상한을 초과하지 않는다(무한 증식 방지).

## 그룹 B — 뉴스 긴급도 재보정

### AC-084-006 (REQ-AI084-005) — co-mention 버스트 → 긴급도 승격 [재현 우선]

- **WHEN** 동일 테마에 대한 최근 기사 폭증(co-mention count ≥ 임계)이 존재하는 상황에서 긴급도 분류가 수행되면, the system **SHALL** 그 테마 기사의 긴급도를 'routine'을 초과하는 등급(≥ important/breaking)으로 승격해야 한다.

_재현 시나리오(비규범):_
- **Given** 동일 테마에 대한 최근 기사 폭증(co-mention count ≥ 임계)이 존재하는 상황(예: 07-22 로봇 테마 15기사, 현재 전부 'routine')
- **When** 긴급도 분류가 수행되면
- **Then** 그 테마 기사의 긴급도가 'routine'을 초과한다(≥ important/breaking). (특성화: 재보정 전 15/15 routine → 재보정 후 버스트 반영 시 상향.)

### AC-084-007 (REQ-AI084-006) — 시장 촉매 커버리지 확장

- **WHEN** 산업 테마 랠리를 시사하는 촉매성 뉴스에 대해 긴급도 분류가 수행되면, the system **SHALL** 그 뉴스를 'routine' 이상으로 분류해야 한다.

_재현 시나리오(비규범):_
- **Given** 산업 테마 랠리를 시사하는 촉매성 뉴스
- **When** 긴급도 분류가 수행되면
- **Then** 'routine' 이상으로 분류된다.

### AC-084-008 (REQ-AI084-007) — routine 오상향 금지 (음성 대조군) [HARD]

- **WHILE** 무촉매 일상(routine) 뉴스 표본(co-mention 버스트 없음, 촉매 키워드 없음)에 대해 재보정된 긴급도 분류가 수행되는 동안, the system **SHALL NOT** 그 표본의 압도적 다수를 breaking/important로 상향해서는 안 된다.

_재현 시나리오(비규범):_
- **Given** 무촉매 일상(routine) 뉴스 표본(co-mention 버스트 없음, 촉매 키워드 없음)
- **When** 재보정된 긴급도 분류가 수행되면
- **Then** 그 표본의 압도적 다수가 여전히 'routine'으로 유지된다(재보정이 routine을 breaking/important로 대량 뒤집지 않음).

### AC-084-009 (REQ-AI084-008, 018) — 게이팅 + 무회귀

- **WHILE** 긴급도 재보정 설정 플래그가 OFF인 동안, the system **SHALL** 긴급도 분류 결과를 기존 레거시 분류와 완전히 동일하게 반환해야 한다(플래그 복귀 = 완전 롤백).
- **WHEN** 기존 긴급도 특성화 테스트 스위트가 실행되면, the system **SHALL** 무회귀로 통과해야 한다.

_재현 시나리오(비규범):_
- **Given** 긴급도 재보정 설정 플래그 OFF
- **When** 긴급도 분류가 수행되면
- **Then** 기존 레거시 분류와 완전 동일(플래그 복귀=완전 롤백). 그리고 기존 긴급도 특성화 테스트가 무회귀로 통과한다.

## 그룹 A — 뉴스 기반 테마 전파 탐지기

### AC-084-010 (REQ-AI084-009, 010) — 키워드 바스켓 앵커 → 미이동 멤버 전파

- **WHEN** 키워드 바스켓의 한 멤버가 앵커로 활성화되고(가격/고긴급 뉴스가 임계 초과) 같은 바스켓의 다른 멤버가 아직 미이동·당일 미시그널이면, the system **SHALL** 그 미이동 멤버에 `signal_type="surge_candidate"` + `surge_metadata.surge_basis=["theme_news_carry"]` 후보를 발행해야 한다.
- **IF** 바스켓 멤버가 이미 급등했거나 당일 이미 신호가 있으면, **THEN** the system **SHALL NOT** 그 멤버에 전파 후보를 발행해서는 안 된다(`existing_ids` 패턴).

_재현 시나리오(비규범):_
- **Given** 키워드 바스켓(예: "로봇")의 한 멤버가 앵커로 활성(가격/고긴급 뉴스가 임계 초과)이고, 같은 바스켓의 다른 멤버는 아직 미이동 + 당일 미시그널
- **When** 그룹 A 탐지기가 실행되면
- **Then** 그 미이동 멤버에 `signal_type="surge_candidate"` + `surge_metadata.surge_basis=["theme_news_carry"]` 후보가 발행된다. 이미 급등했거나 당일 이미 신호가 있는 멤버에는 발행되지 않는다.

### AC-084-011 (REQ-AI084-011) — 테마 활성 확인 게이트 (오전파 통제) [HARD]

- **IF** 바스켓 내 단일 종목만 우연히 이동하여 테마 활성이 확인되지 않으면, **THEN** the system **SHALL NOT** 바스켓 전체로 전파해서는 안 된다.
- **WHEN** 복수 바스켓 멤버가 동반 이동하거나 고긴급 테마 뉴스 + 최소 1개 앵커 이동으로 테마 활성이 확인되면, the system **SHALL** 미이동 멤버에 전파를 수행해야 한다.

_재현 시나리오(비규범):_
- **Given** 바스켓 내 단일 종목만 우연히 이동(테마 활성 미확인)
- **When** 그룹 A 탐지기가 실행되면
- **Then** 바스켓 전체 전파가 발생하지 않는다. 반대로 복수 멤버 동반 이동 또는 고긴급 테마 뉴스 + 앵커 이동이면 전파가 발생한다.

### AC-084-012 (REQ-AI084-012) — 바스켓 데이터 부재 시 안전 no-op [HARD]

- **IF** 대상 종목의 `stocks.keywords`가 NULL/빈 값이면, **THEN** the system **SHALL** 오류 없이 그 종목에 대한 전파를 조용히 건너뛰어야 한다(무해한 no-op, 예외 미발생).

_재현 시나리오(비규범):_
- **Given** `stocks.keywords`가 NULL/빈 값인 종목만 있는 상태(그룹 C 미완)
- **When** 그룹 A 탐지기가 실행되면
- **Then** 오류 없이 조용히 전파를 건너뛴다(빈 바스켓 = 전파 0건, 예외 미발생).

### AC-084-013 (REQ-AI084-013) — same-day 지평 귀속 → 평가 편입 [HARD, 최상위]

- **WHEN** 그룹 A 전파 탐지기가 당일 급등을 예측하는 후보 신호를 `fund_signals`에 영속화하면, the system **SHALL** 그 신호의 `surge_metadata["horizon"]` 필드를 문자열 `"same_day"`로 설정해야 한다(REQ-009의 `surge_basis=["theme_news_carry"]` 명명과 동형의 구체 필드/값 계약).
- **WHILE** same-day 평가가 수행되는 동안, the system **SHALL** `surge_metadata.get("horizon") == "same_day"`를 검사하는 기존 `_is_same_day_event_horizon_signal`(`surge_evaluation_service.py:506-524`) 경로로 그 후보를 same-day 지평에 귀속시켜 표준 T-1→T 버킷 대신 당일(T)의 실제 급등과 비교해야 한다.

**검증(기계적):** 전파로 생성된 `fund_signals` 행을 조회해 영속화된 `surge_metadata->>'horizon' == 'same_day'`(JSON 필드)임을 확인하는 **DB 어서션 테스트**로 검증한다. 트리거 임계(전량 vs 특정 조건)는 OQ-5/DP-5에 위임하나, `horizon="same_day"` 필드/값이 전파-생성 신호에 **설정된다는 계약 자체는 열린 질문이 아니며 본 AC의 확정 통과 기준**이다.

_재현 시나리오(비규범):_
- **Given** 그룹 A가 장중에 당일 급등을 예측하는 후보를 생성하여 `fund_signals`에 영속화
- **When** 그 후보의 `surge_metadata`를 조회하고, 이어서 그 후보가 평가되면
- **Then** 영속화된 `surge_metadata["horizon"] == "same_day"`이고, `_is_same_day_event_horizon_signal` 경로가 이 후보를 same-day 지평으로 인식해 올바른 날(당일)의 실제 급등과 비교한다 — 표준 T-1→T 버킷에 잘못 혼입되지 않는다.

### AC-084-014 (REQ-AI084-014, 015, 016) — 실매매 미트리거 + 기존 경로 불변 [HARD]

- **WHEN** 그룹 A/B/C의 임의 경로가 신호를 생성하면, the system **SHALL NOT** `execute_signal_trade`를 호출하거나 실제 매수를 트리거해서는 안 된다(예측 기록).
- **WHILE** 본 SPEC의 변경이 적용된 동안, the system **SHALL NOT** 기존 7종 탐지기·앙상블 가중치/임계값·스캔 유니버스 구성을 변경해서는 안 된다(diff 0).
- **WHILE** 본 SPEC의 변경이 적용된 동안, the system **SHALL NOT** `detect_theme_group_carry_forward`(계열 그룹)·`ThemeGroup`/`StockThemeGroup` 테이블을 변경해서는 안 된다(diff 0).

_재현 시나리오(비규범):_
- **Given** 그룹 A/B/C의 임의 경로가 신호를 생성
- **When** 그 신호가 처리되면
- **Then** `execute_signal_trade`가 호출되지 않고(예측 기록), 기존 7종 탐지기·앙상블 가중치/임계값·스캔 유니버스·`detect_theme_group_carry_forward`(계열 그룹)·`ThemeGroup`/`StockThemeGroup` 테이블이 전부 불변이다(diff 0).

### AC-084-015 (REQ-AI084-015) — 설정 게이팅 (그룹 A)

- **WHILE** 그룹 A 탐지기 설정 플래그가 OFF인 동안, the system **SHALL** 그룹 A 전파 후보를 0건 발행해야 한다.
- **WHILE** 그룹 A 탐지기 설정 플래그가 OFF인 동안, the system **SHALL** 나머지 파이프라인 거동을 레거시와 동일하게 유지해야 한다(롤백 = 플래그 복귀).

_재현 시나리오(비규범):_
- **Given** 그룹 A 탐지기 설정 플래그 OFF
- **When** 커버리지 확장 파이프라인이 실행되면
- **Then** 그룹 A 전파가 0건이고 나머지 파이프라인 거동은 레거시와 동일(롤백=플래그 복귀).

### AC-084-016 (REQ-AI084-017) — first-mover 비목표 [HARD]

- **WHILE** 본 SPEC의 인수 평가가 수행되는 동안, the system **SHALL NOT** `surge_basis=["theme_news_carry"]` 전파 근거가 없는 first-mover(1차 파동) 후보를 본 SPEC의 recall/precision이 채점되는 `predicted_set`/`actual_set` 멤버십에 포함시켜서는 안 된다.
- **WHEN** 명명된 음성 테스트 `test_first_mover_excluded_from_theme_news_carry_scope`가 실행되면, the system **SHALL** first-mover 종목 코드(동일-순간 뉴스발 상한가, theme_news_carry 전파 근거·same-day 바스켓 근거 부재)가 본 SPEC 채점 `predicted_set`에 나타나지 않음을 확인해야 한다(기존 `excluded_near_limit_up_carry_codes`/`excluded_same_day_event_codes` 제외 패턴, `surge_evaluation_service.py:602-607`과 동형).

_재현 시나리오(비규범):_
- **Given** 동일-순간 뉴스발 상한가의 1차 파동 종목(예: 07-22 09:14 특징주 기사가 이미 완료된 상한가 보도, theme_news_carry 전파 근거 없음)
- **When** 명명된 음성 테스트(`test_first_mover_excluded_from_theme_news_carry_scope`)로 인수 평가 범위를 검사하면
- **Then** 그 first-mover의 사전예측 성능은 본 SPEC의 채점 `predicted_set`/`actual_set`에 포함되지 않는다(측정에서 명시적 제외). 평가 대상은 테마 확인 후 미이동 멤버 전파(2차/3차 파동)에 국한된다.

### AC-084-017 (REQ-AI084-018) — DDD 재현 우선 무회귀

- **IF** 공유 코드 `_classify_urgency`(그룹 B) 또는 `_run_coverage_expansion` 배선(그룹 A)에 변경이 이루어지면, **THEN** the system **SHALL** 그 변경 이전에 현재 거동을 캡처하는 특성화 테스트를 먼저 작성·실행해야 한다(DDD 재현 우선, CLAUDE.md Rule 4).
- **WHEN** 변경 후 전체 백엔드 스위트가 실행되면, the system **SHALL** 기존 긴급도 분류·기존 탐지기 발신을 무회귀로 통과시켜야 한다.

_재현 시나리오(비규범):_
- **Given** 공유 코드 `_classify_urgency`(그룹 B) + `_run_coverage_expansion` 배선(그룹 A)
- **When** 변경 전 특성화 테스트를 선행하고 변경 후 전체 스위트를 실행하면
- **Then** 기존 긴급도 분류·기존 탐지기 발신이 무회귀로 통과하고, 신규 거동은 신규 테스트로 검증된다.

## 엣지 케이스 (Edge Cases)

- **EC-1** 키워드 바스켓이 1개 멤버뿐 → 전파 대상 없음(no-op, 오류 없음).
- **EC-2** 앵커 멤버 자신이 이미 당일 시그널 보유 → 앵커로는 인정하되 자기 자신에 재전파 금지(`emitted`/`existing_ids` 패턴).
- **EC-3** 동일 종목이 복수 바스켓에 속함(예: "로봇" AND "AI") → 크로스바스켓 dedup으로 1회만 전파.
- **EC-4** `_fetch_price_change_sync`가 None 반환(가격 조회 실패) → 그 앵커/멤버 조용히 스킵(기존 관례).
- **EC-5** co-mention 카운트 산정 대상 뉴스가 0건(장 초반) → 긴급도 co-mention 경로 미발화(기존 title 경로만).
- **EC-6** LLM 예산 소진 중 배치 백필 → 규칙/사전 폴백으로 계속(부분 완료, 오류 아님).
- **EC-7** 그룹 C 부분완(일부 종목만 keywords 보유) → 그룹 A는 보유 종목만으로 바스켓 형성(부분 동작, no-op 안전).

## 품질 게이트 (Quality Gates)

- 전체 백엔드 스위트 무회귀: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` PASS(신규 테스트 포함, 기존 실패 0 증가).
- 린트 clean: `cd backend && uv run ruff check .`.
- DDD Reproduction-First: 그룹 A/B 공유 코드 변경 전 RED 특성화 테스트 존재(현재 거동 캡처) → 변경 후 GREEN.
- 신규 테이블/마이그레이션 0(`stocks.keywords` 기존 컬럼 재사용, [X-4]).
- 예측 기록 모드 불변: `execute_signal_trade` 미호출 정적 확인.
- **same-day 지평 계약(AC-084-013 최상위)**: 전파-생성 `fund_signals` 행의 `surge_metadata.horizon == "same_day"` DB 어서션 테스트 통과.
- **first-mover 제외(AC-084-016)**: 명명된 음성 테스트 `test_first_mover_excluded_from_theme_news_carry_scope` 통과.

## Definition of Done (완료 정의)

- [ ] AC-084-001~017 전부 볼드 EARS 정규 문장 기준으로 관찰 가능 증거로 통과.
- [ ] 그룹 C: `stocks.keywords` 배치 백필로 다수 종목 채움(멱등·유계), 지속 태깅 파이프라인 동작, 수동/사용자 키워드 무오염.
- [ ] 그룹 B: co-mention 경로 활성화 + 커버리지 확장으로 07-22 로봇 기사류가 ≥ important, 음성 대조군 routine 유지, 설정 게이팅.
- [ ] 그룹 A: 키워드 바스켓 앵커→미이동 멤버 전파, 테마 활성 확인 게이트, 바스켓 부재 no-op, **same-day 귀속 편입(`surge_metadata.horizon="same_day"` DB 어서션, 최상위 R-4)**, 실매매 미트리거, 기존 경로 불변.
- [ ] 공통: first-mover 비목표([X-1]) 준수 + 명명된 음성 테스트(`test_first_mover_excluded_from_theme_news_carry_scope`) 통과, 계열 그룹 전파 불변([X-3]), 신규 마이그레이션 0([X-4]), 예측 기록 모드 계승([X-5]).
- [ ] 전체 스위트 + 린트 통과, 재현 우선 특성화 선행, 무회귀 확인.
- [ ] 배포 후 관측(후속): 그룹 A 전파 발화 로그 + precision, 그룹 B 긴급도 상향 후 이벤트 재스캔 품질(범위 밖 계측).
