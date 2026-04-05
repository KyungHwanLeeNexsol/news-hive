"""macro_risk.py 단위 테스트.

매크로 리스크 키워드 감지, 슬라이딩 윈도우, 임계치 에스컬레이션,
쿨다운 중복방지, 긍정 맥락 필터링을 검증한다.
REQ-AI-010: detect_macro_risks가 async로 전환됨.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.services.macro_risk import (
    CRITICAL_THRESHOLD,
    WARNING_THRESHOLD,
    _build_description,
    _build_title,
    deactivate_old_alerts,
    detect_macro_risks,
)


# ---------------------------------------------------------------------------
# _build_title / _build_description 순수 함수 테스트
# ---------------------------------------------------------------------------

class TestBuildTitle:
    """_build_title 함수 테스트."""

    def test_warning_level(self):
        """warning 레벨이면 '[주의]' 접두어."""
        result = _build_title("전쟁", 3, "warning")
        assert result == "[주의] '전쟁' 관련 뉴스 3건 감지"

    def test_critical_level(self):
        """critical 레벨이면 '[긴급]' 접두어."""
        result = _build_title("폭락", 7, "critical")
        assert result == "[긴급] '폭락' 관련 뉴스 7건 감지"


class TestBuildDescription:
    """_build_description 함수 테스트."""

    def test_less_than_five_articles(self):
        """기사 5개 미만이면 모든 제목 나열."""
        articles = [type("A", (), {"title": f"뉴스 {i}"})() for i in range(3)]
        result = _build_description(articles)
        assert "뉴스 0" in result
        assert "뉴스 2" in result
        assert "외" not in result

    def test_more_than_five_articles(self):
        """기사 5개 초과이면 최대 5개 + '외 N건' 표시."""
        articles = [type("A", (), {"title": f"뉴스 {i}"})() for i in range(8)]
        result = _build_description(articles)
        assert "뉴스 4" in result
        assert "외 3건" in result


# ---------------------------------------------------------------------------
# detect_macro_risks 통합 테스트 (DB 사용)
# ---------------------------------------------------------------------------

class TestDetectMacroRisks:
    """detect_macro_risks 함수 테스트.

    REQ-AI-010: async 전환 + NLP 분류 mock으로 기존 동작 검증 유지.
    """

    def _create_articles(self, db, make_news, keyword: str, count: int):
        """특정 키워드를 포함하는 뉴스 기사 N개 생성."""
        articles = []
        for i in range(count):
            article = make_news(title=f"{keyword} 관련 뉴스 보도 {i}")
            articles.append(article)
        return articles

    def test_no_articles_returns_empty(self, db):
        """뉴스가 없으면 빈 리스트 반환."""
        alerts = asyncio.run(detect_macro_risks(db))
        assert alerts == []

    def test_below_threshold_no_alert(self, db, make_news):
        """임계치 미만이면 알림 미생성."""
        # WARNING_THRESHOLD(3) 미만인 2개만 생성
        for i in range(WARNING_THRESHOLD - 1):
            make_news(title=f"전쟁 관련 뉴스 {i}")

        alerts = asyncio.run(detect_macro_risks(db))
        assert len(alerts) == 0

    @patch(
        "app.services.macro_risk._classify_macro_severity",
        new=AsyncMock(return_value={
            "severity": "medium", "context_summary": "", "is_false_positive": False,
        }),
    )
    def test_warning_threshold_creates_alert(self, db, make_news):
        """WARNING_THRESHOLD 이상이면 warning 알림 생성."""
        for i in range(WARNING_THRESHOLD):
            make_news(title=f"전쟁 교전 관련 뉴스 {i}")

        alerts = asyncio.run(detect_macro_risks(db))
        assert len(alerts) >= 1

        war_alerts = [a for a in alerts if a.keyword == "전쟁"]
        assert len(war_alerts) == 1
        assert war_alerts[0].level == "warning"

    @patch(
        "app.services.macro_risk._classify_macro_severity",
        new=AsyncMock(return_value={
            "severity": "critical", "context_summary": "", "is_false_positive": False,
        }),
    )
    def test_critical_threshold_creates_critical_alert(self, db, make_news):
        """CRITICAL_THRESHOLD 이상이면 critical 알림 생성."""
        for i in range(CRITICAL_THRESHOLD):
            make_news(title=f"전쟁 교전 포격 뉴스 {i}")

        alerts = asyncio.run(detect_macro_risks(db))
        war_alerts = [a for a in alerts if a.keyword == "전쟁"]
        assert len(war_alerts) == 1
        assert war_alerts[0].level == "critical"

    def test_positive_context_filters_out(self, db, make_news):
        """긍정적 맥락 키워드('반등', '회복' 등)가 있으면 리스크 제외."""
        # 3개 중 2개가 긍정 맥락을 포함하면 1개만 매칭 -> 임계치 미달
        make_news(title="폭락 우려 속 반등 기대")
        make_news(title="증시 급락 후 회복세")
        make_news(title="코스피 급락 패닉셀 발생")

        alerts = asyncio.run(detect_macro_risks(db))
        # 긍정 맥락 2개 제외되면 1개만 남아 임계치(3) 미달
        polrak_alerts = [a for a in alerts if a.keyword == "폭락"]
        assert len(polrak_alerts) == 0

    def test_exclude_context_filters_out(self, db, make_news):
        """개별 기업/비금융 뉴스 제외 패턴이 적용되는지 확인."""
        for i in range(WARNING_THRESHOLD):
            make_news(title=f"매장 폐쇄 관련 폭락 뉴스 {i}")

        alerts = asyncio.run(detect_macro_risks(db))
        polrak_alerts = [a for a in alerts if a.keyword == "폭락"]
        assert len(polrak_alerts) == 0

    @patch(
        "app.services.macro_risk._classify_macro_severity",
        new=AsyncMock(return_value={
            "severity": "medium", "context_summary": "", "is_false_positive": False,
        }),
    )
    def test_cooldown_prevents_duplicate_alert(self, db, make_news, make_macro_alert):
        """쿨다운 기간 내 동일 키워드로 중복 알림 미생성."""
        # 기존 warning 알림이 존재
        make_macro_alert(level="warning", keyword="전쟁")

        # 새로운 전쟁 관련 뉴스 추가
        for i in range(WARNING_THRESHOLD):
            make_news(title=f"전쟁 교전 포격 뉴스 {i}")

        alerts = asyncio.run(detect_macro_risks(db))
        # 쿨다운 중이므로 새 알림은 생성되지 않음
        new_war_alerts = [a for a in alerts if a.keyword == "전쟁"]
        assert len(new_war_alerts) == 0

    @patch(
        "app.services.macro_risk._classify_macro_severity",
        new=AsyncMock(return_value={
            "severity": "critical", "context_summary": "", "is_false_positive": False,
        }),
    )
    def test_cooldown_upgrades_warning_to_critical(self, db, make_news, make_macro_alert):
        """쿨다운 중 기존 warning -> critical 업그레이드."""
        existing = make_macro_alert(level="warning", keyword="전쟁")

        for i in range(CRITICAL_THRESHOLD):
            make_news(title=f"전쟁 교전 포격 뉴스 {i}")

        asyncio.run(detect_macro_risks(db))
        db.refresh(existing)
        assert existing.level == "critical"

    @patch(
        "app.services.macro_risk._classify_macro_severity",
        new=AsyncMock(return_value={
            "severity": "low", "context_summary": "시장 영향 없음", "is_false_positive": True,
        }),
    )
    def test_nlp_false_positive_skips_alert(self, db, make_news):
        """REQ-AI-010: NLP가 거짓 양성으로 판정하면 알림 미생성."""
        for i in range(WARNING_THRESHOLD):
            make_news(title=f"전쟁 교전 뉴스 {i}")

        alerts = asyncio.run(detect_macro_risks(db))
        war_alerts = [a for a in alerts if a.keyword == "전쟁"]
        assert len(war_alerts) == 0


# ---------------------------------------------------------------------------
# deactivate_old_alerts 테스트
# ---------------------------------------------------------------------------

class TestDeactivateOldAlerts:
    """deactivate_old_alerts 함수 테스트.

    SQLite에서 naive/aware datetime 비교 문제를 우회하기 위해
    detect 함수 내부의 datetime.now(timezone.utc)를 naive UTC로 패치한다.
    """

    def _patch_naive_now(self):
        """datetime.now를 naive UTC로 반환하도록 패치 컨텍스트 반환."""
        import app.services.macro_risk as mr_module

        original_now = datetime.now
        original_dt = datetime

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.utcnow()

        return patch.object(mr_module, "datetime", FakeDatetime)

    def test_deactivate_old_active_alerts(self, db, make_macro_alert):
        """24시간 초과 알림 비활성화."""
        old_time = datetime.utcnow() - timedelta(hours=25)
        alert = make_macro_alert(level="warning", keyword="전쟁")
        alert.created_at = old_time
        db.flush()

        with self._patch_naive_now():
            count = deactivate_old_alerts(db)

        assert count >= 1
        db.refresh(alert)
        assert alert.is_active is False

    def test_recent_alerts_not_deactivated(self, db, make_macro_alert):
        """24시간 이내 알림은 비활성화되지 않음."""
        alert = make_macro_alert(level="warning", keyword="전쟁")

        with self._patch_naive_now():
            count = deactivate_old_alerts(db)

        assert count == 0
        db.refresh(alert)
        assert alert.is_active is True
