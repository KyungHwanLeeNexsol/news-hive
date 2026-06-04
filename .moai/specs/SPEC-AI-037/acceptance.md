# SPEC-AI-037 — 인수 기준 (acceptance.md)

각 인수 기준은 EARS 요구사항과 1:1 정렬되며, DB 쿼리 또는 코드 검사(config 로드, 함수 단위 테스트)로 관찰 가능하다.

---

## AC-037-001: 테마 키워드 및 섹터 매핑 확장

**Given** `surge_detection.yaml`이 확장된 상태이고
**When** `get_surge_config()`를 호출하면
**Then** `config.theme_cluster.keywords`에 게임/엔터/조선/해운물류/건설부동산/음식료/화학소재가 포함되고, 전체 keywords 개수가 20개 이상이다.

**And** `config.theme_cluster.sector_theme_map`에 동일 키가 존재하며 각 키의 섹터 리스트가 비어있지 않다.

관찰 방법(코드 검사):
```python
cfg = get_surge_config().theme_cluster
assert len(cfg.keywords) >= 20
for t in ["게임", "엔터", "조선", "해운물류", "건설부동산", "음식료", "화학소재"]:
    assert t in cfg.keywords
    assert len(cfg.sector_theme_map.get(t, [])) > 0
```

---

## AC-037-002: combo_zero_theme_floor 완화

### AC-037-002a (단순 하향, YAML)

**Given** `combo_zero_theme_floor`가 0.55~0.60으로 설정되고
**When** `is_combo_theme_gate_passed`를 `surge_metadata = {"combo_score": 0.0, "theme_cluster_score": 0.58}`로 호출하면
**Then** `True`를 반환한다(완화 전 0.7 기준에서는 `False`였던 케이스).

```python
assert 0.55 <= cfg.adaptive_threshold.combo_zero_theme_floor <= 0.60
meta = {"combo_score": 0.0, "theme_cluster_score": 0.58}
assert is_combo_theme_gate_passed(meta, cfg) is True
```

### AC-037-002b (조건부 적용, 코드)

**Given** 완화된 floor가 적용된 상태에서
**When** 종목의 `volume_z_score >= 3.0`(과열)이고 `combo_score == 0.0`, `theme_cluster_score == 0.58`이면
**Then** 완화 floor가 아닌 기존 0.7 기준이 적용되어 게이트를 통과하지 못한다(`False`).

**And** `volume_z_score < 3.0`(비과열)이면 완화 floor가 적용되어 통과한다(`True`).

---

## AC-037-003: 소형주 시총 필터 조정

### 옵션 (a) 선택 시
**Given** `min_market_cap_krw`가 50000000000(500억)으로 설정되고
**When** detector가 시총 필터를 적용하면
**Then** `min_market_cap_eok == 500`이 되어 시총 500억 이상 종목이 후보에 포함된다.

```python
assert get_surge_config().theme_cluster.min_market_cap_krw == 50_000_000_000
# surge_detector.py:251 → min_market_cap_eok = 500
```

### 옵션 (b) 선택 시
**Given** `min_market_cap_krw`가 1000억으로 유지되고
**When** 시총 800억 종목의 `immediate_disclosure_score >= 0.80`이면
**Then** 시총 필터를 우회하여 후보에 포함된다.

**And** 우회 분기는 예외 발생 시 기존 시총 필터로 폴백한다(예외 전파 없음).

---

## AC-037-004: 테마-섹터 매핑 품질 검증

**Given** `surge_detection.yaml`의 `sector_theme_map`과 `seed/sectors.py`의 `_SNAPSHOT`이 있고
**When** 모든 매핑 섹터명을 정본과 대조하면
**Then** 매핑에 사용된 모든 섹터명이 `_SNAPSHOT` 키에 100% 존재한다(누락 0건).

**And** `음식료품`, `운송장비`, `미디어` 등 정본에 없는 이름이 사용되지 않는다.

관찰 방법(코드 검사):
```python
from app.seed.sectors import _SNAPSHOT
valid = set(_SNAPSHOT.keys())
cfg = get_surge_config().theme_cluster
used = {s for sectors in cfg.sector_theme_map.values() for s in sectors}
missing = used - valid
assert missing == set(), f"정본에 없는 섹터명: {missing}"
```

---

## AC-037-005: 비테마 신호 fast path

**Given** fast path 분기가 게이트 함수에 추가되고
**When** `surge_metadata = {"combo_score": 0.0, "theme_cluster_score": 0.0, "disclosure_pattern_score": 0.72}`로 게이트를 호출하면
**Then** `True`를 반환한다(theme=0이지만 강한 공시 패턴으로 통과).

**And** `surge_metadata = {"combo_score": 0.0, "theme_cluster_score": 0.0, "disclosure_pattern_score": 0.30}`(약신호)이면 `False`를 반환한다(fast path 미충족).

**And** `combo_score >= 0.80` & chase guard 미발동(비과열) 종목도 fast path로 통과한다.

```python
strong = {"combo_score": 0.0, "theme_cluster_score": 0.0, "disclosure_pattern_score": 0.72}
weak = {"combo_score": 0.0, "theme_cluster_score": 0.0, "disclosure_pattern_score": 0.30}
assert is_combo_theme_gate_passed(strong, cfg) is True
assert is_combo_theme_gate_passed(weak, cfg) is False
```

---

## AC-037-006: 회귀 안전성

**Given** 본 SPEC의 모든 변경이 적용된 상태에서
**When** 기존 surge 테스트 스위트를 실행하면(`cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`)
**Then** SPEC-AI-029/030/036 관련 테스트가 전부 통과한다(회귀 0건).

**And** 앙상블 가중치 합산 검증(`validate_ensemble_weights`)이 여전히 통과한다(가중치 미변경).

**And** 코드 변경분의 신규 분기는 메타데이터 누락/파싱 실패 시 예외를 전파하지 않고 기존 동작으로 폴백한다.

```python
# 가중치 합 무변경 확인
w = get_surge_config().ensemble.weights
assert abs(w.theme_cluster + w.volume_news_combo + w.disclosure_pattern + w.legacy_detectors - 1.0) < 0.001
# 예외 격리 확인 — 깨진 메타데이터로도 예외 없이 동작
assert is_combo_theme_gate_passed(None, cfg) is True       # 레거시 폴백
assert is_combo_theme_gate_passed({"foo": "bar"}, cfg) is True  # combo_score 키 없음 → 폴백
```

---

## Edge Cases (경계 조건)

- **EC-1**: `surge_metadata`가 `None`이거나 `combo_score` 키 없음 → 레거시 시그널로 간주, 게이트 통과(기존 동작 유지).
- **EC-2**: 신규 테마 키워드가 뉴스에 등장하지 않으면(min_article_count 미달) 활성 테마에서 제외 — 정상 동작, 신호 없음.
- **EC-3**: `market_cap IS NULL` 종목은 시총 하향과 무관하게 계속 포함됨(surge_detector.py:266 기존 동작).
- **EC-4**: fast path와 SPEC-AI-036 품질 floor가 충돌하는 경우 — 더 엄격한 floor가 우선 적용되어야 함(과진입 방지).
- **EC-5**: `volume_z_score` 지표가 surge_metadata에 없을 때 → 조건부 적용 분기는 완화 floor를 기본 적용(보수적이지 않은 쪽 회피 검토, 구현 시 결정).

---

## Definition of Done

- [ ] AC-037-001 ~ AC-037-006 전부 통과.
- [ ] SP-001 ~ SP-007(spec.md §4) 충족.
- [ ] `get_surge_config()` 로드 성공(Pydantic 검증).
- [ ] sector_theme_map 정본 100% 일치(누락 0건).
- [ ] combo_zero_theme_floor 0.55~0.60 설정.
- [ ] 코드 변경분 전체 예외 격리 + 폴백.
- [ ] 기존 SPEC-AI-029/030/036 테스트 + 신규 테스트 통과.
- [ ] 앙상블 가중치 합 1.0 무변경.
