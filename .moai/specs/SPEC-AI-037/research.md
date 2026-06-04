# SPEC-AI-037 Research — 코드베이스 조사 결과

조사일: 2026-06-04
조사 대상 파일:
- `backend/app/surge_config/surge_detection.yaml`
- `backend/app/surge_config/surge_settings.py`
- `backend/app/services/surge_detector.py`
- `backend/app/services/surge_threshold_service.py`
- `backend/app/services/surge_trading_service.py`
- `backend/app/services/factor_scoring.py`
- `backend/app/models/sector.py`, `backend/app/models/stock.py`, `backend/app/models/fund_signal.py`
- `backend/app/seed/sectors.py` (KRX 섹터명 정본)

> 이 문서는 가정이 아니라 실제 파일 읽기 결과를 기록한다. 모든 줄 번호는 조사 시점 기준이며, 코드 변경 시 달라질 수 있으니 작업 전 재확인 필요.

---

## 1. 현재 13개 테마 (정확한 값)

`surge_detection.yaml` 3번 줄, `theme_cluster.keywords`:

```yaml
keywords: ["반도체", "배터리", "수소", "전기차", "AI", "로봇", "방위산업", "바이오", "원전", "항공", "5G", "보안칩", "K뷰티"]
```

`sector_theme_map` (4~17번 줄) — 테마별 매핑 섹터:

| 테마 | 매핑 섹터 |
|------|-----------|
| 반도체 | IT서비스, 전자장비와기기, 반도체와반도체장비, 전기장비, 디스플레이장비및부품 |
| 배터리 | 화학, 전기장비, 자동차부품 |
| 수소 | 화학, 에너지장비및서비스 |
| 전기차 | 자동차, 자동차부품, 전기장비 |
| AI | IT서비스, 소프트웨어, 통신장비, 전자장비와기기, 전자제품, 복합기업 |
| 로봇 | IT서비스, 기계, 전자장비와기기, 전자제품 |
| 방위산업 | 기계, 우주항공과국방 |
| 바이오 | 제약, 생물공학, 생명과학도구및서비스, 건강관리장비와용품, 건강관리업체및서비스 |
| 원전 | 전기유틸리티, 에너지장비및서비스 |
| 항공 | 항공사, 항공화물운송과물류 |
| 5G | 통신장비, IT서비스, 소프트웨어, 복합기업 |
| 보안칩 | 통신장비, 반도체와반도체장비, 소프트웨어, IT서비스 |
| K뷰티 | 화장품, 건강관리업체및서비스, 섬유,의류,신발,호화품 |

---

## 2. KRX 섹터명 정본 (`seed/sectors.py` `_SNAPSHOT`, 127~206번 줄)

DB의 `sectors.name` 값은 `seed/sectors.py`의 `_SNAPSHOT` 딕셔너리에서 생성된다(출처: Naver Finance GICS, 2026-02-24 스냅샷). 테마-섹터 매핑은 반드시 이 정본 이름과 **정확히 일치**해야 한다. detector가 `db.query(Sector).filter(Sector.name.in_(all_sector_names))`로 조회하기 때문에, 철자가 다르면 그냥 0건 매칭된다.

전체 67개 섹터 중 REQ-037 테마 확장과 관련된 주요 섹터:

| 신규 테마 후보 | 정본 섹터명 (존재함) | naver_code |
|----------------|----------------------|-----------|
| 게임 | `게임엔터테인먼트` | 263 |
| 엔터 | `방송과엔터테인먼트`, `양방향미디어와서비스`, `광고` | 285 / 300 / 310 |
| 조선 | `조선` | 291 |
| 해운/물류 | `해운사`, `항공화물운송과물류`, `운송인프라`, `도로와철도운송` | 323 / 326 / 296 / 329 |
| 건설/부동산 | `건설`, `부동산`, `건축자재`, `건축제품` | 279 / 280 / 289 / 320 |
| 음식료 | `식품`, `음료`, `식품과기본식료품소매`, `담배` | 268 / 309 / 302 / 275 |
| 화학소재 | `화학`, `철강`, `비철금속`, `종이와목재`, `포장재` | 272 / 304 / 322 / 318 / 311 |

### [중요] task에서 제안했으나 DB에 존재하지 않는 섹터명

다음 섹터명은 task 요구사항 문구에 등장하지만 `_SNAPSHOT`에 **없으므로 사용 불가** (사용 시 0건 매칭):

- `음식료품` → 존재 안 함. 정본은 `식품`(268), `음료`(309).
- `운송장비` → 존재 안 함. 조선은 `조선`(291), 자동차는 `자동차`(273)/`자동차부품`(270).
- `미디어` → 존재 안 함. 정본은 `방송과엔터테인먼트`(285), `양방향미디어와서비스`(300).
- `섬유의류` → 정확한 정본은 `섬유,의류,신발,호화품`(274) — 쉼표 포함.

이 발견 때문에 REQ-037-004(매핑 품질 검증)는 단순 추가가 아니라 **정본 대조 필수 작업**이다.

### 현재 YAML 매핑 검증 (정본 대조)

현재 13개 테마의 매핑 섹터를 정본과 대조한 결과 — **모두 정본에 존재**(0건 매칭 위험 없음). 단, `전자제품`(307)과 `전자장비와기기`(282)는 둘 다 존재하므로 AI/로봇 매핑은 유효하다. 즉, 기존 13개 테마 매핑에는 깨진 이름이 없다. 신규 테마 추가 시에만 정본 대조가 새로 필요하다.

---

## 3. theme_cluster 탐지 흐름 (`surge_detector.py`)

테마 클러스터 탐지 함수(약 188~389번 줄):

1. **뉴스 윈도우 조회** (203~209): `cluster_window_hours`(48h) 내 NewsArticle 최대 1000건.
2. **키워드 카운트** (215~221): 각 기사 title+content+summary에서 `cfg.keywords`의 키워드 포함 여부 카운트.
3. **활성 테마 식별** (223~227): `min_article_count`(2건) 이상인 키워드만 활성 테마로 채택.
4. **테마→섹터 매핑** (235~247): 활성 테마의 `sector_theme_map` 섹터 수집.
5. **시총 필터 종목 조회** (249~269): `min_market_cap_krw`(1000억) → 억원 환산(`// 100_000_000` = 1000억원), `Sector.name.in_(...)` 조회. `market_cap IS NULL`인 종목도 포함(266번 줄 `or_(... , Stock.market_cap.is_(None))`).
6. **종목별 점수 계산** (278~386):
   - `theme_base = min(1.0, cnt / 10)` (298) — 키워드 기사 수 10건 → 1.0 만점.
   - 섹터 관련성: 종목 섹터가 테마 섹터 목록에 있으면 1.0, 아니면 0.5 (293~296).
   - 종목 전용 기사 있으면 60/40 블렌딩, 없으면 0.5× 페널티 (321~326).
   - 가격 보너스 +0.10 (`abs(change_rate) > 3.0`, 333~344).
   - 감성 배율 (348~354).
   - 최종 clamp 0~1 (356).

**[핵심] 코드 변경 없이 YAML만으로 확장 가능한 항목**:
- `keywords` 리스트에 새 키워드 추가 → 코드 변경 불필요 (216번 줄이 `cfg.keywords`를 동적 순회).
- `sector_theme_map`에 새 테마 키 + 섹터 리스트 추가 → 코드 변경 불필요 (238번 줄이 `cfg.sector_theme_map.get(theme, [])`로 동적 조회).
- `min_market_cap_krw` 값 변경 → 코드 변경 불필요 (251번 줄이 설정값을 읽음).

즉, **REQ-037-001(키워드 확장), REQ-037-003(시총 조정), REQ-037-004(매핑 품질)는 전부 YAML-only로 구현 가능**하다. Pydantic 모델 `ThemeClusterConfig`(surge_settings.py 30~38)도 `keywords: list[str]`, `sector_theme_map: dict[str, list[str]]`로 정의되어 있어 임의 확장을 수용한다.

---

## 4. 앙상블 스코어링 (`compute_ensemble_score`, 947~1006번 줄)

```python
weighted_sum = (
    w.theme_cluster * candidate.theme_cluster_score        # 0.28
    + w.volume_news_combo * candidate.combo_score          # 0.35
    + w.disclosure_pattern * best_disclosure_score          # 0.20
    + w.legacy_detectors * candidate.legacy_score           # 0.17
)
```

- `best_disclosure_score = max(pattern_score, immediate_disclosure_score)` (967).
- 그룹 단위 컨센서스 배율: news(theme+combo)/disclosure/technical 3개 그룹, 활성 그룹 2개 → ×1.30, 3개 이상 → ×1.55 (979~994).
- `final_score = min(1.0, weighted_sum * multiplier)` (996).
- 가중치 합산 검증: `validate_ensemble_weights`(surge_settings.py 216~225)가 4개 가중치 합 = 1.0 (±0.001) 강제. **가중치 변경 시 반드시 합 1.0 유지**.

비테마 종목(theme_cluster_score=0)이라도 combo/disclosure/legacy 점수가 강하면 `weighted_sum`이 임계값을 넘을 수 있다. 즉 **신호 생성 단계에서는 비테마 종목이 원천 차단되지 않는다**. 차단은 아래 4번의 실행 단계 게이트에서 발생한다.

---

## 5. [핵심 발견] `combo_zero_theme_floor`는 신호 생성이 아니라 **매수 실행 단계** 게이트

이 SPEC의 핵심 오해 방지 포인트. `combo_zero_theme_floor`(0.7)는 `surge_detector.py`에서 적용되지 **않는다**. 적용 위치는 두 곳:

### (a) 게이트 함수: `is_combo_theme_gate_passed` (`surge_threshold_service.py` 238~272)

```python
floor = config.adaptive_threshold.combo_zero_theme_floor   # 0.7
if surge_metadata is None: return True            # 레거시 → 통과
if "combo_score" not in surge_metadata: return True  # 레거시 → 통과
combo_score = float(surge_metadata.get("combo_score", 0.0))
theme_score = float(surge_metadata.get("theme_cluster_score", 0.0))
if combo_score > 0.0: return True                 # combo 있으면 게이트 미적용
return theme_score >= floor                        # combo=0 → theme >= 0.7 이어야 통과
```

### (b) 호출 위치: `execute_buy_orders` (`surge_trading_service.py` 692~707)

```python
if _adaptive_exec_cfg.enabled:
    ...
    if not _combo_gate(_raw_meta_dict, _surge_cfg_exec):
        # skipped, reason=combo_theme_gate (combo=0, theme<0.7)
        skipped += 1
        continue
```

**의미**: `combo_score == 0.0`이고 `theme_cluster_score < 0.7`인 종목은 매수 단계에서 무조건 제외된다. theme=0인 순수 비테마 종목은 disclosure/legacy 점수가 아무리 강해도 이 게이트를 통과 못 한다(theme 0 < 0.7). → **REQ-037-002(floor 완화), REQ-037-005(비테마 fast path)의 정확한 타깃은 이 게이트 함수**.

### 실행 단계 게이트 순서 (execute_buy_orders)

1. 적응형 임계값 비교: `probability < _effective_prob_threshold` → skip (683~690). 임계값은 `get_today_threshold`로 당일 저장값 사용(재산출 없음, SPEC-AI-029 REQ-006).
2. `is_combo_theme_gate_passed` → skip (692~707).
3. 일일 한도/포지션/섹터 한도 등 후속 체크 (709~).

> 참고: SPEC-AI-036(floor gate)이 이 위에 추가로 얹히는 품질 floor를 도입한다고 메모에 기록됨. 동일 함수 영역을 건드릴 수 있으므로 작업 시 SPEC-AI-036 변경분과 충돌 여부 확인 필요.

---

## 6. 적응형 임계값 (`compute_adaptive_threshold`, `surge_threshold_service.py` 61~)

- `config.adaptive_threshold` 설정 사용(yaml 96~108).
- `enabled=False`이면 정적 `min_score_for_signal`(0.45) 사용.
- 승률 창(5), 승률 floor(0.40), 레짐 배율(BEAR 1.2 / SIDEWAYS 1.0 / BULL 0.9), 최종 clamp 0.45~0.85.
- `combo_zero_theme_floor`(0.7)는 `AdaptiveThresholdConfig`의 필드로 정의됨(surge_settings.py 188) → **YAML 값 변경만으로 floor 조정 가능, 코드 변경 불필요**.

즉, REQ-037-002의 "단순 floor 하향(0.7→0.55)"은 YAML-only로 가능. 단, "조건부 적용(volume_z_score < 3.0일 때만)"이나 "비테마 fast path"는 게이트 함수 로직 변경이 필요 → 코드 변경.

---

## 7. 시총 필터 (`min_market_cap_krw`)

- 현재 값: `100000000000` (= 1000억원), yaml 20번 줄.
- 적용 위치: `surge_detector.py` 251번 줄 `min_market_cap_eok = cfg.min_market_cap_krw // 100_000_000` → 1000(억원).
- 종목 필터: 266번 줄 `or_(Stock.market_cap >= min_market_cap_eok, Stock.market_cap.is_(None))`.
- **값 변경은 YAML-only**(Pydantic `min_market_cap_krw: int`). 50000000000(500억)으로 낮추면 더 많은 소형주 포함.
- "immediate_disclosure_score >= 0.80 종목 시총 우회"는 detector의 시총 필터 쿼리 자체를 바꿔야 하므로 코드 변경 필요(현재 쿼리는 시총 조건을 SQL WHERE에 직접 둠).

---

## 8. composite_score / factor_scoring 흐름

- `factor_scoring.py`의 `compute_composite_score`(316~), `build_factor_scores_json`(346~)은 4-factor 가중합으로 0~100 스케일 composite를 만든다 — 이는 **LLM 경로**(`fund_manager.generate_signal`)용이다.
- surge_candidate 경로(surge_detector.py)는 composite_score를 설정하지 않으며, 대신 `surge_metadata.surge_probability_score`(0~1)에 앙상블 점수를 저장한다(1238~1241).
- `theme_cluster_score`는 `factor_scoring`으로 직접 흐르지 않고, surge 경로의 `compute_ensemble_score` 안에서만 가중된다. → **REQ-037은 factor_scoring.py를 건드릴 필요 없음** (surge 경로 전용).

---

## 9. fund_signals 스키마 정정

- task 문구는 "fund_signals.sector_name column"을 언급하나, `fund_signal.py`에 **`sector_name` 컬럼이 존재하지 않는다**(grep 0건).
- 섹터는 `Stock.sector_id` → `Sector.name`(sector.py 13번 줄, `String(100)`)으로만 연결된다.
- 따라서 REQ-037-004의 검증 기준은 "fund_signals.sector_name과의 일치"가 아니라 **"`seed/sectors.py` `_SNAPSHOT` 정본 이름과의 일치"**로 잡아야 한다(acceptance.md 반영).

---

## 10. YAML-only vs 코드 변경 분류 (요약)

| 요구사항 | 구현 방식 | 근거 |
|----------|-----------|------|
| REQ-037-001 키워드/테마 확장 | **YAML-only** | keywords/sector_theme_map 동적 순회 (surge_detector.py 216, 238) |
| REQ-037-002a floor 단순 하향(0.7→0.55) | **YAML-only** | AdaptiveThresholdConfig.combo_zero_theme_floor 필드 (surge_settings.py 188) |
| REQ-037-002b floor 조건부 적용 | **코드 변경** | is_combo_theme_gate_passed 로직 추가 (surge_threshold_service.py 238~272) |
| REQ-037-003a 시총 하향(1000억→500억) | **YAML-only** | min_market_cap_krw 필드, SQL 필터가 설정값 사용 |
| REQ-037-003b 공시 강신호 시총 우회 | **코드 변경** | detector 시총 쿼리(surge_detector.py 261~269) 분기 추가 |
| REQ-037-004 매핑 품질 검증/수정 | **YAML-only** | _SNAPSHOT 대조 후 sector_theme_map 수정 |
| REQ-037-005 비테마 fast path | **코드 변경** | 게이트 함수에 bypass 분기 추가 |
| REQ-037-006 회귀 안전성 | 검증/테스트 | 기존 SPEC 게이트 호출부 무변경 확인 |

**우선순위 함의**: YAML-only 변경(001/002a/003a/004)을 먼저 적용해 위험을 최소화하고, 코드 변경(002b/003b/005)은 예외 격리하여 후속 적용.
