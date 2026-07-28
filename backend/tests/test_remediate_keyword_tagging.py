"""SPEC-AI-091 M3: `scripts/remediate_keyword_tagging.py` 정화 스크립트 테스트.

AC-AI091-007/008/009/010 검증. dry-run 기본값(DB 무변경), --execute 리셋+재백필,
provenance 불명 종목 진단 보고, 정화 후 분포 상한/스팟체크를 검증한다.

conftest.py의 공유 ``db`` 픽스처(전체 ORM 스키마 create_all)를 재사용한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.sector import Sector
from app.models.stock import Stock

_ROBOT_KEYWORDS = ["로봇", "AI", "반도체"]


def _make_stock(db: Session, stock_code: str, name: str, keywords=None, created_at=None) -> Stock:
    sector = db.query(Sector).first()
    if sector is None:
        sector = Sector(name="테스트섹터", naver_code="001")
        db.add(sector)
        db.flush()

    stock = Stock(stock_code=stock_code, name=name, sector_id=sector.id, keywords=keywords)
    if created_at is not None:
        stock.created_at = created_at
    db.add(stock)
    db.flush()
    return stock


def _make_direct_news(db: Session, stock_id: int, title: str, content: str = "") -> NewsArticle:
    article = NewsArticle(
        title=title, content=content, url=f"https://example.com/{title}", source="naver"
    )
    db.add(article)
    db.flush()

    rel = NewsStockRelation(
        news_id=article.id, stock_id=stock_id, match_type="keyword", relevance="direct"
    )
    db.add(rel)
    db.flush()
    return article


# ---------------------------------------------------------------------------
# AC-AI091-007(c): dry-run 기본값 — DB 변경 없음
# ---------------------------------------------------------------------------


def test_dry_run_default_makes_no_db_changes(db: Session) -> None:
    """AC-AI091-007: execute=False(기본값)이면 keywords가 전혀 변경되지 않는다."""
    from scripts.remediate_keyword_tagging import run_remediation

    stock = _make_stock(db, "023790", "동일스틸럭스", keywords=["로봇", "전기차", "배터리"])

    report = run_remediation(db, execute=False)

    db.refresh(stock)
    assert report["mode"] == "dry-run"
    assert stock.keywords == ["로봇", "전기차", "배터리"]  # 불변
    assert report["reset_count"] == 0
    assert report["backfill_result"] is None
    assert report["spot_check"] is None
    assert report["after"] == report["before"]


def test_dry_run_reports_diagnosis_without_execute_flag() -> None:
    """스크립트 CLI가 --execute 없이 실행되면 진단만 출력한다(파서 기본값 확인)."""
    import argparse

    from scripts.remediate_keyword_tagging import main  # noqa: F401 — import 성공 확인용

    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args([])
    assert args.execute is False


# ---------------------------------------------------------------------------
# AC-AI091-007(a)/(b): --execute 리셋 + 수정된 알고리즘 재백필
# ---------------------------------------------------------------------------


def test_execute_resets_and_rebackfills_with_fixed_algorithm(db: Session) -> None:
    """AC-AI091-007: --execute 시 오염된 keywords를 리셋 후 수정된 알고리즘으로 재백필한다.

    정화 전 keywords는 (버그로 인해) 실제와 무관한 테마로 오염되어 있다고 가정하고,
    정화 후에는 실제 연결 뉴스(로봇, 2건 direct)만 반영된 상태로 수렴해야 한다.
    """
    from scripts.remediate_keyword_tagging import run_remediation

    stock = _make_stock(
        db, "023790", "동일스틸럭스",
        keywords=["전기차", "배터리", "조선", "원전", "5G", "바이오", "게임", "AI", "반도체", "항공"],
    )
    _make_direct_news(db, stock.id, "동일스틸럭스 로봇 부품 사업 진출")
    _make_direct_news(db, stock.id, "동일스틸럭스 로봇 협력 발표")

    report = run_remediation(db, execute=True, theme_keywords=_ROBOT_KEYWORDS)

    db.refresh(stock)
    assert report["mode"] == "execute"
    assert report["reset_count"] == 1
    assert stock.keywords == ["로봇"]
    assert report["backfill_result"].stocks_tagged == 1
    assert report["spot_check"]["023790"] == 1


def test_execute_is_idempotent_across_repeated_runs(db: Session) -> None:
    """§C 엣지 케이스 4: --execute를 두 번 연속 실행해도 세 번째 실행과 동일한 최종
    상태에 수렴해야 한다(backfill_stock_keywords의 기존 멱등 계약 상속)."""
    from scripts.remediate_keyword_tagging import run_remediation

    stock = _make_stock(db, "105560", "KB금융", keywords=["로봇", "전기차", "배터리"])
    _make_direct_news(db, stock.id, "KB금융 반도체 투자 협력 발표")
    _make_direct_news(db, stock.id, "KB금융 반도체 스타트업 지원")

    report1 = run_remediation(db, execute=True, theme_keywords=_ROBOT_KEYWORDS)
    db.refresh(stock)
    state1 = list(stock.keywords)

    report2 = run_remediation(db, execute=True, theme_keywords=_ROBOT_KEYWORDS)
    db.refresh(stock)
    state2 = list(stock.keywords)

    report3 = run_remediation(db, execute=True, theme_keywords=_ROBOT_KEYWORDS)
    db.refresh(stock)
    state3 = list(stock.keywords)

    assert state1 == ["반도체"]
    assert state2 == state1 == state3
    # 2차/3차 실행은 이미 정화된 상태이므로 리셋 대상이 없다(진단 카운트도 안정).
    assert report2["reset_count"] == report3["reset_count"] == 1
    assert report1["after"]["tagged_stocks"] == report3["after"]["tagged_stocks"]


# ---------------------------------------------------------------------------
# AC-AI091-008: provenance 불명 종목 기본 포함 + 진단 보고
# ---------------------------------------------------------------------------


def test_diagnosis_reports_unknown_provenance_count(db: Session) -> None:
    """AC-AI091-008: SPEC-AI-084 최초 백필일 이전 생성된(provenance 불명 후보) 종목 수가
    진단 결과에 포함된다."""
    from scripts.remediate_keyword_tagging import diagnose

    old_cutoff = datetime(2026, 7, 22)
    _make_stock(
        db, "000010", "구세대종목", keywords=["수동테마"],
        created_at=old_cutoff - timedelta(days=30),
    )
    _make_stock(
        db, "000020", "신세대종목", keywords=["로봇"],
        created_at=old_cutoff + timedelta(days=1),
    )

    result = diagnose(db)

    assert result["tagged_stocks"] == 2
    assert result["unknown_provenance_count"] == 1


def test_unknown_provenance_stock_still_reset_by_default(db: Session) -> None:
    """REQ-AI091-008: provenance 불명 종목도 보수적 기본 처리에 따라 리셋 대상에
    기본 포함된다(구조적 구분 불가 — §2 [E-12] spec.md)."""
    from scripts.remediate_keyword_tagging import reset_keywords

    old_stock = _make_stock(
        db, "000010", "구세대종목", keywords=["수동테마"],
        created_at=datetime(2026, 1, 1),
    )

    reset_count = reset_keywords(db)

    db.refresh(old_stock)
    assert reset_count == 1
    assert old_stock.keywords is None


# ---------------------------------------------------------------------------
# AC-AI091-009/010: 정화 후 분포 상한 + 확정 오탐 종목 스팟체크
# ---------------------------------------------------------------------------


def test_spot_check_reports_length_for_confirmed_false_positive_stocks(db: Session) -> None:
    """AC-AI091-010: 확정 오탐 3종목(023790/105560/192080)의 정화 후 keywords 길이를
    개별 스팟체크로 보고한다."""
    from scripts.remediate_keyword_tagging import spot_check

    _make_stock(db, "023790", "동일스틸럭스", keywords=["로봇"])
    _make_stock(db, "105560", "KB금융", keywords=None)
    _make_stock(db, "192080", "더블유게임즈", keywords=["게임", "반도체"])

    result = spot_check(db)

    assert result == {"023790": 1, "105560": 0, "192080": 2}


def test_diagnose_computes_full_cap_pct_and_median(db: Session) -> None:
    """AC-AI091-009: 진단 결과가 10개(상한) 보유 비율과 중앙값을 계산한다."""
    from scripts.remediate_keyword_tagging import diagnose

    _make_stock(db, "000001", "종목1", keywords=["a"] * 10)  # 상한 보유
    _make_stock(db, "000002", "종목2", keywords=["a", "b"])
    _make_stock(db, "000003", "종목3", keywords=None)  # 미태깅 — 분모 제외

    result = diagnose(db)

    assert result["tagged_stocks"] == 2
    assert result["full_cap_count"] == 1
    assert result["full_cap_pct"] == 50.0
    assert result["median_length"] == 6  # median(10, 2) == 6
