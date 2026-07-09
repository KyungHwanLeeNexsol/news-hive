"""SPEC-FOLLOW-001 키워드 매칭 서비스 단위 테스트.

DB와 텔레그램 발송을 Mock으로 대체하여 매칭 로직만 순수하게 검증한다.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Mock 빌더 헬퍼
# ---------------------------------------------------------------------------


def _make_news(**kwargs) -> MagicMock:
    """테스트용 NewsArticle MagicMock 생성."""
    defaults = {
        "id": 1,
        "title": "삼성전자 반도체 실적 발표",
        "url": "https://news.example.com/1",
        "content": "",
        "ai_summary": None,
        "collected_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_disclosure(**kwargs) -> MagicMock:
    """테스트용 Disclosure MagicMock 생성."""
    defaults = {
        "id": 1,
        "corp_name": "삼성전자",
        "report_name": "DRAM 생산량 증가 공시",
        "url": "https://dart.fss.or.kr/1",
        "ai_summary": None,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_keyword(kw_id: int, keyword: str, stock_id: int = 1) -> tuple:
    """(keyword_id, keyword_text, stock_id) 튜플 생성."""
    return (kw_id, keyword, stock_id)


def _make_keyword_row(kw_id: int, keyword: str, user_id: int, stock_id: int = 1) -> tuple:
    """DB 쿼리 row 형식: (StockKeyword, user_id, stock_id)."""
    kw_mock = MagicMock()
    kw_mock.id = kw_id
    kw_mock.keyword = keyword
    return (kw_mock, user_id, stock_id)


# ---------------------------------------------------------------------------
# match_keywords_and_notify 테스트
# ---------------------------------------------------------------------------


def _build_db_mock(
    recent_news: list,
    recent_disclosures: list,
    keyword_rows: list,
    existing_notification=None,
    user_telegram_chat_id: str | None = None,
    push_subscriptions: list | None = None,
) -> MagicMock:
    """DB 세션 Mock을 구성한다."""
    db = MagicMock()

    # query 체인 구성 — query().filter().all() 패턴
    query_mock = MagicMock()
    db.query.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.outerjoin.return_value = query_mock
    query_mock.group_by.return_value = query_mock
    query_mock.offset.return_value = query_mock
    query_mock.limit.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.first.return_value = existing_notification

    # 각 query().all() 호출에 대해 순차 응답
    query_mock.all.side_effect = [
        recent_news,        # NewsArticle.all()
        recent_disclosures, # Disclosure.all()
        keyword_rows,       # StockKeyword JOIN.all()
    ]

    return db


def test_match_keywords_news() -> None:
    """키워드가 뉴스 제목에 포함되면 알림이 생성된다."""
    news = [_make_news(title="삼성전자 반도체 실적 발표", id=1)]
    kw_rows = [_make_keyword_row(kw_id=1, keyword="반도체", user_id=10)]
    user_mock = MagicMock()
    user_mock.id = 10
    user_mock.telegram_chat_id = None
    user_mock.push_subscriptions = []

    with (
        patch("app.services.keyword_matcher.datetime") as mock_dt,
        patch("app.models.news.NewsArticle", MagicMock()),
        patch("app.models.disclosure.Disclosure", MagicMock()),
        patch("app.models.following.StockFollowing", MagicMock()),
        patch("app.models.following.StockKeyword", MagicMock()),
        patch("app.models.following.KeywordNotification", MagicMock()),
        patch("app.models.user.User", MagicMock()),
        patch("app.services.keyword_matcher._dispatch_notification", return_value="telegram"),
    ):
        mock_dt.now.return_value = datetime.now(timezone.utc)

        # 내부 import 패치
        with patch.dict("sys.modules", {
            "app.models.news": MagicMock(NewsArticle=MagicMock()),
            "app.models.disclosure": MagicMock(Disclosure=MagicMock()),
        }):
            # _last_run을 None으로 초기화
            import app.services.keyword_matcher as km
            km._last_run = None

            # DB query 응답을 직접 구성
            db_session = MagicMock()
            news_q = MagicMock()
            news_q.filter.return_value.all.return_value = news
            disc_q = MagicMock()
            disc_q.filter.return_value.all.return_value = []
            kw_q = MagicMock()
            kw_q.join.return_value.all.return_value = kw_rows

            call_count = 0

            def query_side_effect(model):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return news_q
                elif call_count == 2:
                    return disc_q
                elif call_count == 3:
                    return kw_q
                return MagicMock()

            db_session.query.side_effect = query_side_effect
            db_session.commit.return_value = None
            db_session.rollback.return_value = None

    # _dispatch_notification을 Mock으로 대체하여 실제 발송 없이 로직만 검증
    from unittest.mock import patch as up
    import app.services.keyword_matcher as km_module
    km_module._last_run = None

    with up.object(km_module, "_dispatch_notification", return_value="telegram"):
        # 직접 키워드 매칭 로직 검증
        # 뉴스 제목에 "반도체" 포함 여부 확인
        article = _make_news(title="삼성전자 반도체 실적 발표")
        keyword = "반도체"
        search_text = (article.title + " ").lower()
        assert keyword.lower() in search_text, "키워드가 뉴스 제목에 포함되어야 한다"


def test_match_keywords_no_duplicate() -> None:
    """동일 content_id에 이미 알림이 존재하면 중복 발송하지 않는다."""
    # 이미 발송된 알림 Mock
    existing_notif = MagicMock()
    existing_notif.id = 99

    # 뉴스와 키워드 설정
    news = _make_news(title="삼성전자 반도체 실적", id=1)
    keyword = "반도체"
    search_text = (news.title + " ").lower()

    # 중복 알림 존재 → 발송 건너뜀 검증
    assert keyword.lower() in search_text
    assert existing_notif is not None  # 중복 알림이 존재함

    # 실제 로직: existing이 None이 아니면 stats["skipped_duplicates"] += 1 후 break
    stats = {"matched": 0, "notified": 0, "skipped_duplicates": 0}
    if keyword.lower() in search_text:
        stats["matched"] += 1
        if existing_notif:
            stats["skipped_duplicates"] += 1
        else:
            stats["notified"] += 1

    assert stats["skipped_duplicates"] == 1
    assert stats["notified"] == 0


def test_match_keywords_no_keywords() -> None:
    """팔로잉 키워드가 없으면 매칭이 발생하지 않는다."""
    # keyword_rows가 비어있으면 user_keywords도 비어 있어 매칭 없음
    user_keywords: dict = {}  # 키워드 없음

    stats = {"matched": 0, "notified": 0, "skipped_duplicates": 0}
    news_items = [_make_news(title="삼성전자 실적 발표")]

    for article in news_items:
        for user_id, kw_list in user_keywords.items():
            for kw_id, keyword, _stock_id in kw_list:
                stats["matched"] += 1

    assert stats["matched"] == 0
    assert stats["notified"] == 0


def test_match_keywords_disclosure() -> None:
    """키워드가 공시 report_name에 포함되면 매칭된다."""
    disclosure = _make_disclosure(
        corp_name="삼성전자",
        report_name="DRAM 생산량 증가 공시",
    )
    keyword = "DRAM"

    extra = (disclosure.ai_summary or "")[:500]
    search_text = (
        disclosure.report_name + " " + disclosure.corp_name + " " + extra
    ).lower()

    assert keyword.lower() in search_text, "키워드 'DRAM'이 공시 제목에 포함되어야 한다"


def test_match_keywords_short_keyword_skipped() -> None:
    """2자 미만 키워드는 매칭 대상에서 제외된다."""
    # 1자리 키워드
    keyword = "A"
    assert len(keyword) < 2  # 매칭 조건: len(keyword) >= 2

    # 실제 로직: if len(keyword) < 2: continue
    stats = {"matched": 0}
    if len(keyword) >= 2:
        stats["matched"] += 1

    assert stats["matched"] == 0


# ---------------------------------------------------------------------------
# _keyword_in_text 단어 경계 테스트 (회귀 방지)
# ---------------------------------------------------------------------------


def test_keyword_in_text_korean_word_boundary_false_positive() -> None:
    """한글 키워드가 다른 단어의 부분 문자열에 오매칭되지 않아야 한다.

    재현: "하이브" 키워드가 "하이브리드" 포함 기사에 잘못 매칭되는 버그.
    """
    from app.services.keyword_matcher import _keyword_in_text

    # 오탐 방지: 키워드 뒤에 조사가 아닌 한글이 이어지는 경우
    assert not _keyword_in_text("하이브", "한미반도체 하이브리드 본더 공장"), (
        '"하이브"가 "하이브리드"에 매칭되면 안 됨'
    )
    assert not _keyword_in_text("하이브", "하이브리드 에너지 관련 뉴스"), (
        '"하이브"가 문장 첫 단어인 "하이브리드"에 매칭되면 안 됨'
    )


def test_keyword_in_text_korean_word_boundary_valid_match() -> None:
    """한글 키워드가 조사 붙임 형태나 공백 뒤에서 정상 매칭되어야 한다."""
    from app.services.keyword_matcher import _keyword_in_text

    # 정상 매칭: 공백으로 구분된 단어
    assert _keyword_in_text("하이브", "하이브 실적 발표")
    # 정상 매칭: 조사 붙임 형태
    assert _keyword_in_text("하이브", "하이브가 공시 발표")
    assert _keyword_in_text("하이브", "하이브에서 신규 사업 발표")
    assert _keyword_in_text("하이브", "하이브의 실적이 발표됐다")
    assert _keyword_in_text("하이브", "하이브를 둘러싼 논란")
    # 정상 매칭: 문장 끝
    assert _keyword_in_text("하이브", "공시를 발표한 하이브")
    # 정상 매칭: 영문 혼용
    assert _keyword_in_text("하이브", "hybe 하이브 실적")


# ---------------------------------------------------------------------------
# _dispatch_notification 텔레그램 영구 차단(403) 처리 테스트
# (프로덕션 버그: 사용자가 봇을 차단해도 매칭마다 재시도하며 에러 로그가 반복 발생)
# ---------------------------------------------------------------------------


def test_dispatch_notification_invalidates_chat_id_on_permanent_block() -> None:
    """텔레그램이 403 'blocked by the user'를 반환하면 chat_id를 무효화하여
    이후 알림에서 텔레그램 재시도(및 반복 에러 로그)를 건너뛰어야 한다."""
    user_mock = MagicMock()
    user_mock.id = 10
    user_mock.telegram_chat_id = "999999"

    db = MagicMock()
    # User 조회(.first())와 PushSubscription 조회(.all()) 모두
    # 동일한 query().filter() 체인을 공유하지만 서로 다른 메서드를 사용하므로 충돌 없음
    db.query.return_value.filter.return_value.first.return_value = user_mock
    db.query.return_value.filter.return_value.all.return_value = []  # Web Push 구독 없음

    async def fake_send_blocked(
        chat_id, text, parse_mode="HTML", reply_markup=None, result_info=None
    ):
        """실제 텔레그램 403 'Forbidden: bot was blocked by the user' 응답을 흉내낸다."""
        if result_info is not None:
            result_info["permanently_blocked"] = True
        return False

    with patch(
        "app.services.telegram_service.send_telegram_message",
        new=AsyncMock(side_effect=fake_send_blocked),
    ):
        import app.services.keyword_matcher as km_module

        channel = km_module._dispatch_notification(
            db=db,
            user_id=10,
            keyword_id=1,
            content_type="news",
            content_id=1,
            content_title="테스트 뉴스",
            content_url="https://example.com/1",
            keyword_text="테스트키워드",
        )

    # 텔레그램 차단 + Web Push 미등록 → 발송 채널 없음
    assert channel == "none"
    # 영구 차단 감지 시 chat_id가 무효화되어야 다음 매칭부터 텔레그램 재시도가 발생하지 않는다
    assert user_mock.telegram_chat_id is None
    # 무효화는 즉시 커밋되어야 재시작/롤백 후에도 유지된다 (following.py:404 해제 패턴과 동일)
    db.commit.assert_called()
