# Plan: SPEC-AI-078 — Pool A 공시 후보 impact_score 기반 우선순위 절단 교정

## 목표

`build_scan_universe()`의 Pool A 후보 조회에 `impact_score` 기반 정렬을 도입해, 절단이 불가피한 날
**고impact 공시가 우선 잔존**하도록 한다. `max_scan_universe`(SPEC-AI-065)·quota 메커니즘
(SPEC-AI-076)·`pool_a` raw 카운트 의미는 전부 불변으로 유지한다.

## 기술 접근 (Technical Approach)

### 1. Pool A 조회 쿼리 정렬 도입 (핵심 변경 — 단일 지점)

**현행** (`surge_detector.py:4230-4239`):

```python
disclosure_rows = (
    db.query(Disclosure.stock_code)
    .filter(
        Disclosure.rcept_dt == today_str,
        Disclosure.stock_code.isnot(None),
    )
    .distinct()
    .all()
)
pool_a_raw = [r.stock_code for r in disclosure_rows if r.stock_code]
```

**문제**: `ORDER BY` 부재 → DB 반환 순서. 또한 단순 `SELECT DISTINCT stock_code ORDER BY impact_score`는
Postgres에서 부적합(DISTINCT 시 ORDER BY 식이 select 목록에 있어야 함) + 한 종목이 복수 공시를 가질 때
어느 impact로 정렬할지 모호.

**해결**: 종목별 `MAX(impact_score)` 집계 + NULL-안전 내림차순 정렬:

```python
from sqlalchemy import func

if config.pool_a_rank_by_impact:
    max_impact = func.max(Disclosure.impact_score)
    disclosure_rows = (
        db.query(Disclosure.stock_code, max_impact.label("max_impact"))
        .filter(
            Disclosure.rcept_dt == today_str,
            Disclosure.stock_code.isnot(None),
        )
        .group_by(Disclosure.stock_code)
        # NULL-안전: 미스코어링 공시를 뒤로(NULLS LAST 동급). 아래 "NULL 정렬 이식성" 참조.
        .order_by(max_impact.is_(None).asc(), max_impact.desc())
        .all()
    )
    pool_a_raw = [r.stock_code for r in disclosure_rows if r.stock_code]
else:
    # 레거시 경로 (백워드 호환 탈출구, REQ-AI078-005)
    disclosure_rows = (
        db.query(Disclosure.stock_code)
        .filter(
            Disclosure.rcept_dt == today_str,
            Disclosure.stock_code.isnot(None),
        )
        .distinct()
        .all()
    )
    pool_a_raw = [r.stock_code for r in disclosure_rows if r.stock_code]
```

- **변경 범위**: 오직 `pool_a_raw` 생성 지점(`:4229-4245`). 이후 `pool_a_codes` 누적 루프, quota 예약
  (`:4387-4427`), 절단 슬라이스(`:4427`), `pool_counts`(`:4373-4377`)는 **전부 무변경**. 정렬은 리스트
  순서만 바꾸므로 이후 로직에 투명하다.

### 2. NULL 정렬 이식성 (Postgres + SQLite 테스트) [주의]

- **1순위(이식성 우선)**: `order_by(max_impact.is_(None).asc(), max_impact.desc())`. NULL-여부 불리언
  (False=0 → 비-NULL 먼저)으로 1차 정렬 후 점수 내림차순. Postgres·SQLite 양쪽에서 결정적. 테스트가
  SQLite로 돌기 때문에 이 방식을 채택한다.
- **대안(Postgres 네이티브)**: `order_by(max_impact.desc().nullslast())`. SQLAlchemy가 `NULLS LAST`로
  컴파일. SQLite는 3.30.0+(2019)부터 지원하나 환경 편차 위험 → 1순위 방식을 권장.
- 두 방식 모두 동률(같은 impact) 시 순서는 미지정 — 동률 종목 간 순서는 신호 품질상 무차별하므로
  허용(단, 테스트는 동률 케이스에 순서 의존성을 넣지 않는다).

### 3. 설정 토글 추가 (백워드 호환, SPEC-AI-076 패턴 계승)

- `surge_settings.py` `SurgeDetectionConfig`에 `pool_a_rank_by_impact: bool = True` 추가.
- `surge_detection.yaml`에 대응 키(기본 `true`) + 주석(비활성 시 레거시 DB-순서 복귀) 추가.
- **기본값 True**(신규 거동 ON) — SPEC-AI-076이 floors를 기본 비-0(20/30, 신규 거동 ON)으로 배포한
  선례와 정합. False로 두면 REQ-AI078-005 (a) 레거시 경로.

### 4. 관측성 로깅 (REQ-AI078-007, P2 선택)

- 절단 발생 시(`len(final_universe) < 합산 후보 수`) `[스캔유니버스]` 로그에 Pool A 컷오프 impact
  (잔존 최저) 및 탈락 최고 impact를 추가. `entry_pool_map` + 정렬된 `pool_a_codes`로 in-memory 계산.
- 절단 없으면 로깅 생략. 신규 컬럼/마이그레이션 없음.

## 변경 대상 파일 (예상)

| 파일 | 변경 내용 | 규모 |
|------|-----------|------|
| `backend/app/services/surge_detector.py` | Pool A 조회 정렬(`:4229-4245`) + 토글 분기 + P2 로깅 + MX 태그 | 중 |
| `backend/app/surge_config/surge_settings.py` | `pool_a_rank_by_impact: bool = True` 필드 추가 | 소 |
| `backend/app/surge_config/surge_detection.yaml` | `pool_a_rank_by_impact: true` + 주석 | 소 |
| `backend/tests/test_spec_ai_065.py` | 재현 우선 characterization(058730형 replay) + 정렬/NULL/토글/무절단 테스트 | 중 |

**신규 테이블/마이그레이션/스키마 변경 없음.** 매매 로직 무변경.

## 마일스톤 (우선순위 기반, 시간 추정 없음)

1. **Priority High — 재현 테스트 (RED)**: 07-08형 시나리오(Pool A raw > 슬롯, 고impact 공시가 저impact
   공시들 뒤)에서 "현행 무순위 절단으로 058730형 종목이 `final_universe`에 부재"를 포착하는 실패 테스트
   작성·확인. (REQ-006)
2. **Priority High — 정렬 구현 (GREEN)**: Pool A 조회에 종목별 MAX impact + NULL-안전 정렬 도입, 토글
   분기 추가. 재현 테스트 통과 확인. (REQ-001/002/003)
3. **Priority High — 불변식 회귀 가드**: `max_scan_universe`/quota/`pool_a` raw 카운트 diff 0 검증
   테스트 + 기존 065/076/유니버스 스위트 무회귀 확인. (REQ-004)
4. **Priority Medium — 백워드 호환**: 토글 비활성 = 레거시 DB-순서 동등, 무절단 = 결과 집합 동등 테스트.
   설정 필드/YAML 추가. (REQ-005)
5. **Priority Low — 관측성 로깅**: 절단 컷오프 impact 로깅 + MX 태그(NOTE/ANCHOR 보강). (REQ-007)

## 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| NULL 정렬 역효과(Postgres 기본 NULLS FIRST) | 미스코어링 공시가 최우선 잔존 → 교정 무력화 | `is_(None).asc()` 선행 정렬키로 NULL을 명시적 후순위(REQ-002). 테스트에 NULL-혼재 케이스 포함 |
| SQLite/Postgres 정렬 방언 편차 | 테스트(SQLite)와 프로덕션(PG) 거동 불일치 | 이식성 우선 `is_(None).asc()` 방식 채택(양쪽 결정적). `nullslast()` 미사용 |
| DISTINCT→GROUP BY 전환 부작용 | 종목 집합(절단 전)이 달라질 위험 | `GROUP BY stock_code`는 `DISTINCT stock_code`와 동일 집합 산출(길이 불변). 테스트로 집합 동등 확인 |
| 스코어링 타이밍(방금 수집된 NULL 공시) | 최근 공시가 후순위로 밀림 | research.md 제약 #1 확인: 유니버스 빌드는 크롤 잡 이후 별도 잡 → 대부분 이미 스코어링됨. NULL은 배제 아닌 후순위 유지라 손실 없음 |
| 동률 impact 종목 순서 미지정 | 동률 종목 간 임의 절단 | 신호 품질상 무차별 → 허용. 테스트는 동률에 순서 의존성 배제 |

## 검증 명령 (CLAUDE.local.md)

```bash
cd backend && uv run pytest tests/test_spec_ai_065.py tests/test_spec_ai_076.py \
  tests/test_surge_universe_members.py tests/test_surge_universe_pool_bugfix.py --tb=short -q
cd backend && uv run pytest tests/ --tb=short -q -m "not slow" -n 4   # 전체 회귀(xdist 포함)
cd backend && uv run ruff check . && uv run mypy app/
```

## 선행/관계 SPEC

- **SPEC-AI-065**(선행/불변): `max_scan_universe`(150) 상한 소유. 본 SPEC은 읽어 사용만.
- **SPEC-AI-076**(선행/불변): quota 메커니즘(`pool_b_min_slots`/`pool_c_min_slots`) 소유. 본 SPEC의
  정렬은 그 이전 단계라 상호 독립. 백워드 호환 토글 패턴을 계승.
- **SPEC-AI-073**(맥락): DART 복구로 Pool A 절단 압력을 최초 발생시킨 새 사실.
