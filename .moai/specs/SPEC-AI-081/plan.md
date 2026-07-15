# Plan: SPEC-AI-081 — 공시 충격 스코어링 flat-base 카테고리 콘텐츠 인식 정밀화

## 목표

`score_disclosure_impact()`(`backend/app/services/disclosure_impact_scorer.py`)의 flat-base 경로
(주요사항보고/지분공시)에 대해, (1) 기존 Tier 키워드 메커니즘의 커버리지 갭을 메우고(최대주주
지배권 변경 인식), (2) `dart_crawler.py` 자체 분류기의 우선순위 버그로 "주요사항보고"에 갇힌
희석성 증권 발행 결정을 스코어링 단계에서 로컬 재분류한다. 신규 설정 플래그로 게이팅하며 기본값은
`false`(레거시 완전 보존).

## 기술 접근 (Technical Approach)

### 1. 설정 플래그 추가 (SPEC-AI-079/080 패턴 계승)

`backend/app/surge_config/surge_settings.py`의 `SurgeDetectionConfig`에 신규 하위 설정 클래스 추가:

```python
class DisclosureContentAwareScoringConfig(BaseModel):
    """SPEC-AI-081: 공시 충격 스코어링 flat-base 카테고리 콘텐츠 인식 정밀화 설정.

    enabled=False(기본값)이면 score_disclosure_impact()의 flat-base 경로(주요사항보고/지분공시)가
    레거시 거동(Tier1/2/3 키워드 목록 + 기존 report_type 기준 base)을 완전히 유지한다.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-081 — 기본값 false(레거시 완전 보존, 공유 고fan-in 함수 변경 원칙)
    # @MX:SPEC: SPEC-AI-081 REQ-AI081-004
    enabled: bool = False
```

`SurgeDetectionConfig`에 `disclosure_content_aware_scoring: DisclosureContentAwareScoringConfig =
DisclosureContentAwareScoringConfig()` 필드 추가. `surge_detection.yaml`에 대응 키 + 주석 추가
(기존 `immediate_surge`/`relative_scoring` 블록과 나란히).

### 2. 최대주주 지배권 변경 키워드 커버리지 확장 (REQ-001)

**현행** `_KEYWORD_TIER1`(disclosure_impact_scorer.py:89)은 리터럴 `"최대주주 변경"`(공백 포함)만
포함 — DART 표준 제목 `"최대주주등소유주식변동신고서"`와 불일치(공백 없음, "변동" vs "변경").

**해결**: `_get_keyword_tier_multiplier()`(`:96-109`) 내부에서 매칭 전 텍스트를 기존
`_ROUTINE_GOVERNANCE_KEYWORDS` 매칭이 이미 사용하는 정규화 패턴과 일관되게 처리:

```python
def _get_keyword_tier_multiplier(report_name: str, ai_summary: str | None) -> float:
    text = report_name + " " + (ai_summary or "")
    normalized = text.replace(" ", "").replace("·", "")
    if any(kw in text for kw in _KEYWORD_TIER1) or _is_controlling_shareholder_change(normalized):
        return 2.0
    ...
```

신규 헬퍼(예: `_is_controlling_shareholder_change(normalized_text: str) -> bool`)는 "최대주주" +
{"변동", "변경", "교체"} 어근 공존을 정규화된 텍스트에서 판정한다(리터럴 부분 문자열 매칭 스타일
유지, §2 [A-2]). 신규 함수 위치는 `_get_keyword_tier_multiplier` 인접(단일 지점 변경).

**게이팅**: `disclosure_content_aware_scoring.enabled=false`일 때는 이 신규 판정을 건너뛰고
기존 14개 키워드 목록만 검사(레거시 완전 동등).

### 3. 희석성 증권 발행결정 로컬 재분류 (REQ-002)

**현행** `dart_crawler._REPORT_TYPE_PATTERNS`(dart_crawler.py:29-72)는 순서 있는 리스트이며
`("주요사항보고서", "주요사항보고")`(`:36`)가 `("전환사채", "발행공시")`(`:45`) 등보다 먼저 체크되어,
"주요사항보고서(전환사채권발행결정)" 같은 제목이 "주요사항보고"로 확정되고 뒤쪽 패턴에 도달하지
못한다. **이 파일/저장값은 변경하지 않는다**([X-2]) — 대신 `score_disclosure_impact()` 내부에
로컬 재분류 단계를 추가:

```python
# SPEC-AI-081: dart_crawler._REPORT_TYPE_PATTERNS의 발행공시 매핑 키워드를 스코어링 전용으로
# 로컬 재사용(단일 출처 위반 아님 — dart_crawler.py 저장값 자체는 미변경, 국소 재분류만)
_ISSUANCE_DILUTION_KEYWORDS = [
    "전환사채", "신주인수권", "교환사채", "유상증자", "무상증자", "파생결합증권",
]

def score_disclosure_impact(disclosure, market_cap_億):
    ...
    cfg = get_surge_config().disclosure_content_aware_scoring
    effective_report_type = report_type
    if (
        cfg.enabled
        and report_type == "주요사항보고"
        and any(kw in report_name for kw in _ISSUANCE_DILUTION_KEYWORDS)
    ):
        effective_report_type = "발행공시"

    # 이하 base 조회 등은 report_type 대신 effective_report_type 사용
    base = _BASE_IMPACT_BY_TYPE.get(effective_report_type, 10)
    ...
```

**주의**: 조기 반환 경로(루틴 캡, 계약공시, 실적변동)는 `effective_report_type` 도입 이전에 이미
분기되므로 영향 없음(§2 [E-5], 상호 배타적). `effective_report_type`은 **함수 로컬 변수**이며
`disclosure.report_type`(저장 필드) 자체를 갱신하지 않는다(REQ-006 (c) 불변식).

- **설계 결정 (확정, spec.md REQ-AI081-002 참조)**: 재분류된 공시는 "발행공시"의 flat `-10` base를
  그대로 상속받는다(별도의 완화된 로직 신설 없음). 단순성 우선 원칙(CLAUDE.md Agent Core Behavior
  #4)에 따라 확정 — [X-9]가 명시하듯 이 재분류의 목적은 "038880을 상향시키는 것"이 아니라 "일관된
  처리"이므로, -10을 그대로 상속해도 REQ-002의 의도를 충족한다. 이 결정으로 spec.md 舊 OQ-1은
  Open Questions에서 제거되었다.

### 4. ai_summary 비의존성 검증 (REQ-003)

REQ-001/002의 신규 로직은 모두 `report_name`을 1차 신호원으로 사용하며(§2 [E-3]), `ai_summary`는
기존 `report_name + ai_summary` 병합 검색 텍스트 패턴을 통해 우연히 채워진 경우의 방어적 보강으로만
읽힌다. 이를 검증하기 위해, 동일한 `report_name`(006340형/038880형)에 대해 `ai_summary=None`인
경우와 관련 없는 임의 텍스트로 채워진 경우 각각 `score_disclosure_impact()`를 호출해 반환값이
동일함을 확인하는 테스트를 추가한다(acceptance.md AC-081-009). 신규 별도 `ai_summary` 전용 판정
경로는 만들지 않는다(기존 병합 검색 텍스트 패턴 재사용, 회귀 없음).

### 5. 오탐 방지 회귀 가드 (REQ-005)

465770형(범용 캐치올, "투자판단관련주요경영사항")은 신규 키워드(§2/§3)에도 매칭되지 않음을 명시
테스트로 고정 — flat 20 유지가 "버그"가 아니라 "의도된 하한"임을 코드 주석(`@MX:NOTE`)과 테스트로
동시에 문서화.

### 6. 특성화 테스트 선행 (REQ-007, DDD ANALYZE-PRESERVE)

변경 전 다음을 characterization test로 고정:
- 3개 실증 사례(465770/038880/006340) 스타일 입력에 대한 **수정 전** flat 점수(20/20/25) 재현.
- `process_disclosure_impact()`의 임계 분기(≥20 스냅샷 / ≥25 gap_pullback / ≥30 섹터파급 트리거
  / SPEC-AI-080 `immediate_surge.min_impact`)가 **로직 자체는 무변경**임을 확인하는 통합 테스트 —
  새 점수값이 이 로직에 어떻게 흘러들어가는지만 검증, 임계 상수/분기 조건은 그대로.
- 기존 `TestScoreDisclosureImpact`/`TestExtractContractAmount`/`TestDetectUnreflectedGap`/
  `TestDetectSectorRipple` 전량 무회귀.

## 변경 대상 파일 (예상)

| 파일 | 변경 내용 | 규모 |
|------|-----------|------|
| `backend/app/services/disclosure_impact_scorer.py` | 최대주주 키워드 정규화 매칭 헬퍼 추가, 희석성 발행결정 로컬 재분류 분기, MX 태그 | 중 |
| `backend/app/surge_config/surge_settings.py` | `DisclosureContentAwareScoringConfig` 클래스 + `SurgeDetectionConfig` 필드 추가 | 소 |
| `backend/app/surge_config/surge_detection.yaml` | `disclosure_content_aware_scoring: {enabled: false}` 키 + 주석 | 소 |
| `backend/tests/test_disclosure_impact_scorer.py` | 재현 테스트(3사례) + 신규 키워드/재분류/ai_summary 비의존성/오탐방지/토글 테스트 | 중 |
| `backend/tests/test_disclosure_impact_scorer_immediate_surge.py` | 하위 소비자(즉시발화 게이팅) 무회귀 확인 테스트 추가(필요 시) | 소 |

**신규 테이블/마이그레이션 없음.** `dart_crawler.py`/`Disclosure.report_type` 저장 로직 무변경.
매매 로직 무변경.

## 마일스톤 (우선순위 기반, 시간 추정 없음)

1. **Priority High — 특성화 테스트 (ANALYZE-PRESERVE)**: 3개 실증 사례 스타일 입력의 수정 전 flat
   거동(20/20/25) 재현 테스트 작성·통과 확인. 하위 소비자 임계 분기 통합 테스트 작성. (REQ-007)
2. **Priority High — 설정 플래그 도입**: `DisclosureContentAwareScoringConfig` 추가, 기본값 false.
   (REQ-004)
3. **Priority High — 최대주주 키워드 커버리지 확장 (IMPROVE)**: 정규화 매칭 헬퍼 추가, 006340형
   재현 테스트 통과(flat 25 → 신규 정규화 매칭 시 Tier1 배수 적용 결과로 상향) 확인. (REQ-001)
4. **Priority High — 희석성 발행결정 로컬 재분류 (IMPROVE)**: `effective_report_type` 로컬 재분류
   분기 추가, 038880형 재현 테스트로 "발행공시 경로로 전환됨"(차등 처리, 상향 아님) 확인. (REQ-002)
5. **Priority High — ai_summary 비의존성 검증**: 006340형/038880형 report_name에 대해 `ai_summary=
   None`과 관련 없는 임의 텍스트로 채워진 경우 각각 `score_disclosure_impact()` 반환값이 동일함을
   확인하는 테스트 작성·통과. (REQ-003)
6. **Priority High — 오탐 방지 회귀 가드**: 465770형(무신호)과 기존 루틴 캡 사례가 flat 기본값을
   유지함을 명시 테스트로 고정. (REQ-005)
7. **Priority High — 불변식 회귀 가드**: 다른 5개 report_type 카테고리, 하위 소비자 게이팅 로직,
   `report_type` 저장값·`dart_crawler.py` diff 0 검증. 기존 전체 스위트 무회귀. (REQ-006)
8. **Priority Medium — 백워드 호환 검증**: 토글 비활성 시 레거시 완전 동등(모든 카테고리) 테스트.
   (REQ-004)
9. **Priority Low — 관측성 로깅**: 재분류/키워드 확장 트리거 시 로그 추가 + MX 태그(NOTE/ANCHOR
   보강). (REQ-008)

## 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 최대주주 키워드 정규화 과대 매칭 | 루틴 지분공시까지 상향(오탐) | "최대주주"+변경/변동 어근 공존으로 매칭 범위 한정, 루틴 캡이 이미 조기 반환하여 상호 배타적(§2 [E-5]), 비-최대주주 지분공시 테스트로 오탐 없음 확인(REQ-005) |
| 희석성 재분류가 038880을 상향시키지 못함(기대치 불일치) | 사용자/오케스트레이터 기대와 acceptance 결과 편차 | [X-9]/[R-3]에 명시적으로 문서화, acceptance.md에서 "차등 처리"로 검증 범위 조정 |
| 공유 고 fan-in 함수(`score_disclosure_impact`) 변경의 하위 소비자 회귀 | 즉시발화/섹터파급/gap_pullback 게이팅 오동작 | REQ-007 특성화 테스트 + 전체 회귀 스위트(기본 + `-n 4`) |
| `effective_report_type` 로컬 변수 도입이 실수로 `disclosure.report_type` 저장을 건드릴 위험 | report_type 소비자(disclosures 라우터 필터, SPEC-AI-028) 회귀 | 코드 리뷰 체크리스트 항목화 + `disclosure.report_type` 값 diff 0 단정 테스트(REQ-006 (c)) |
| ai_summary 우연 존재 케이스의 회귀 | 기존 실적변동/계약공시 경로가 영향받을 위험 | 신규 로직은 flat-base 경로 진입 이후에만 적용(§2 [E-5] 상호 배타 구조 유지), 기존 실적변동/계약 테스트 무회귀 확인 |

## 검증 명령 (CLAUDE.local.md)

```bash
cd backend && uv run pytest tests/test_disclosure_impact_scorer.py \
  tests/test_disclosure_impact_scorer_immediate_surge.py --tb=short -q
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"          # 전체 회귀
cd backend && uv run pytest tests/ --tb=short -q -m "not slow" -n 4     # 전체 회귀(xdist 병렬)
cd backend && uv run ruff check . && uv run mypy app/
```

## 선행/관계 SPEC

- **SPEC-AI-004(선행)**: `score_disclosure_impact()` 원 소유. 본 SPEC은 flat-base 경로만 확장.
- **SPEC-AI-051(선행, 메커니즘 불변)**: Tier1/2/3 키워드-배수 메커니즘 소유. 본 SPEC은 키워드
  커버리지만 확장.
- **SPEC-AI-080(인접, 게이팅 로직 불변)**: `immediate_surge.min_impact` 게이팅의 입력값
  (`impact_score`)만 본 SPEC의 영향을 받을 수 있음.
- **SPEC-AI-079(참고 패턴)**: 공유 고 fan-in 코드 변경 시 기본값 OFF 롤아웃 패턴 계승.
