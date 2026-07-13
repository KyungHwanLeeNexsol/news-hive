# Research: SPEC-AI-078 — Pool A 공시 후보 무순위 절단 교정

## 배경

2026-07-13 세션에서 "왜 recall이 07-06 제외 전부 0%인가"를 SSH 프로덕션 DB 직접 조회 + 로컬 코드
대조로 조사. `predicted_count`가 `actual_surge_count` 대비 극히 낮은 근본원인을 코드 레벨로 확정.

## 근본원인

`backend/app/services/surge_detector.py:build_scan_universe()` (line 4188-4455)

Pool A(당일 DART 공시 종목) 조회 쿼리(line 4230-4239):

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
```

**`.order_by()`가 없다.** `pool_a_codes`는 쿼리 반환 순서(=DB 내부 순서, 사실상 공시 접수 순서에
가까움) 그대로 사용된다.

최종 조합·절단 로직(line 4408-4427):

```python
universe_ordered = (
    reserved_b_list + reserved_c_list + pool_a_codes
    + b_remaining + c_remaining + [existing...]
)
# 중복 제거 후
final_universe = universe_dedup[:max_universe]  # max_universe = config.max_scan_universe (150)
```

Pool A raw 후보가 `max_universe`에서 Pool B/C 예약분(SPEC-AI-076 `pool_b_min_slots`/`pool_c_min_slots`)을
뺀 실질 슬롯(~100~130)을 넘으면, **impact_score·계약규모·시가총액 등 신호 품질과 무관하게** 잘려나가는
공시가 결정된다.

## 실증 데이터 (2026-07-08)

- Pool A raw=232건, 그중 `disclosure_impact_scorer.score_disclosure_impact()` 산출 `impact_score>=20`
  (baseline 스냅샷 문턱, `disclosure_impact_scorer.py:377`)만 155건 — 이미 실질 슬롯 초과.
- `surge_universe_members`(trading_date=2026-07-08) 직접 조회: 그날 미탐지(FN) 표본 5종목 중
  **001210(금호전기) 1건만 스캔 유니버스 포함**(entry_pool=pool_a), 나머지 4종목(058730, 263800, 189330,
  214330)은 유니버스 자체에 없었음.
- **058730(다스코)**: `disclosures` 테이블에 07-08 당일 `report_type="주요사항보고"`,
  `report_name="단일판매ㆍ공급계약체결"`, `impact_score=20`(baseline 문턱 정확히 통과)로 **정상
  스코어링까지 됐음에도** 최종 유니버스에서 잘림 — 정렬 없는 절단이 원인임을 직접 증명하는 사례.

## 관련 기존 SPEC과의 관계

- **SPEC-AI-076**(풀별 최소 슬롯 예약)은 Pool B/C가 Pool A에 밀려 0이 되는 "풀 간(cross-pool) 굶주림"을
  고쳤다. 이번 이슈는 **Pool A 풀 내부(intra-pool) 절단**의 별개 문제 — SPEC-AI-076이 다루지 않은 영역.
- SPEC-AI-065가 `max_scan_universe`(150) 상한 자체를 소유(불변) — 이번 SPEC은 상한을 바꾸지 않고
  상한 초과 시 "무엇이 잘리는가"의 우선순위만 도입한다.

## 제약/리스크

1. **타이밍 확인 완료(저위험)**: `scheduler.py:_run_dart_crawl()`가 크롤 직후 동기적으로 공시 충격
   스코어링까지 완료한다(2026-07-13 실제 운영 로그로 확인: "DART: page 21/21" → "공시 충격 스코어링
   완료: 16건" → "DART crawl completed" 순서, 동일 잡 실행 내). `_run_surge_universe_build()`
   (scheduler.py:1206, `build_scan_universe` 호출부)는 별도 잡으로 크롤 잡(30분 간격) 이후 실행되므로,
   유니버스 빌드 시점엔 그날 수집된 공시 대부분이 이미 `impact_score`를 갖고 있다고 볼 수 있다. 다만
   극히 최근(같은 스캔 사이클 내 방금 들어온) 공시는 스코어링 타이밍상 NULL일 가능성이 완전히 배제되진
   않음 — 아래 NULL 정렬 처리로 커버.
2. **NULL 정렬 위험**: PostgreSQL `ORDER BY impact_score DESC`는 기본적으로 NULL을 맨 앞에 정렬한다
   (`NULLS FIRST`가 DESC 기본값). 스코어링 안 된(NULL) 공시가 오히려 최우선 순위를 차지하는 역효과를
   피하려면 `NULLS LAST`를 명시하거나 COALESCE 처리가 필요하다.
3. **SPEC-AI-076의 quota 배분 계약과의 상호작용**: 정렬은 Pool A 원본 리스트(`pool_a_codes`) 생성
   시점에 적용하면 되므로, 이후 quota 배분 로직(reserved_b/c, 잔여 채움) 구조는 변경 불필요 — 낮은
   침습도로 수정 가능.
4. **회귀 가드**: `surge_universe_pool_history`의 `pool_a_count`(raw, pre-truncation) 의미는 절대
   변경 금지(AC-076 계열 기존 계약, MX:REASON 주석 line 4371-4372).

## 제안 방향 (설계는 manager-spec이 최종 결정)

Pool A raw 쿼리에 `Disclosure.impact_score`를 조인하여 `ORDER BY impact_score DESC NULLS LAST`(또는
동급 처리) 추가. impact_score가 아직 없는 신규 공시(스코어링 파이프라인 지연)에 대한 처리 정책도
함께 정의 필요(예: 낮은 우선순위로 뒤에 배치하되 완전 배제하지 않음).

## 이번 SPEC 범위 밖 (별도 백로그, 사용자 확인 후 후속 SPEC으로 분리)

이번 세션에서 함께 발견했으나 이 SPEC에 포함하지 않음 (스코프 규율 유지):

1. `OPENAI_API_KEY` 프로덕션 미설정 — 코드가 아닌 시크릿/운영 이슈, SPEC으로 해결 불가
2. LLM 미스분석 5종목 고정 샘플링 — 별도 개선 과제
3. 263800/189330 LLM 미스분석 근거 데이터 그라운딩 의심(환각 가능성 미확정) — 별도 조사 필요

상세: `~/.claude/projects/{project-hash}/memory/project_pool_a_unranked_truncation_2026_07_13.md`
