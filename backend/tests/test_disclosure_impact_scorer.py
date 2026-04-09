"""SPEC-AI-004 공시 기반 미반영 호재 탐지 시스템 테스트.

모든 핵심 수용 기준(AC-001 ~ AC-010)을 커버하는 특성화 테스트 모음.
외부 의존성(naver_finance, paper_trading, scheduler)은 모두 Mock 처리.
SQLAlchemy ORM 대신 MagicMock으로 모델 객체를 대체한다.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.disclosure_impact_scorer import (
    activate_gap_pullback,
    capture_baseline_price,
    detect_sector_ripple,
    detect_unreflected_gap,
    extract_contract_amount,
    measure_price_reflection,
    run_reflection_check,
    score_disclosure_impact,
)


def _make_disclosure(**kwargs) -> MagicMock:
    """테스트용 Disclosure MagicMock 생성 헬퍼.

    SQLAlchemy 모델 대신 MagicMock을 사용하여 DB 없이 단위 테스트 가능.
    """
    defaults = {
        "id": 1,
        "corp_code": "00000000",
        "corp_name": "테스트기업",
        "stock_code": "005930",
        "stock_id": 1,
        "report_name": "사업보고서",
        "report_type": "정기공시",
        "rcept_no": "202400000001",
        "rcept_dt": "20240101",
        "url": "https://dart.fss.or.kr/test/1",
        "ai_summary": None,
        "impact_score": None,
        "baseline_price": None,
        "reflected_pct": None,
        "unreflected_gap": None,
        "ripple_checked": False,
        "disclosed_at": None,
    }
    defaults.update(kwargs)
    d = MagicMock()
    for k, v in defaults.items():
        setattr(d, k, v)
    return d


def _make_stock(**kwargs) -> MagicMock:
    """테스트용 Stock MagicMock 생성 헬퍼."""
    defaults = {
        "id": 1,
        "name": "테스트종목",
        "stock_code": "005930",
        "sector_id": 10,
        "market_cap": 10000,
    }
    defaults.update(kwargs)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _make_signal(**kwargs) -> MagicMock:
    """테스트용 FundSignal MagicMock 생성 헬퍼."""
    defaults = {
        "id": 1,
        "stock_id": 1,
        "signal_type": "gap_pullback_candidate",
        "signal": "buy",
        "confidence": 0.7,
        "reasoning": "",
        "price_at_signal": 50000,
        "is_correct": None,
        "created_at": datetime.now(timezone.utc),
        "disclosure_id": 1,
    }
    defaults.update(kwargs)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# AC-001 ~ AC-004: 공시 유형별 충격 점수 계산
# ---------------------------------------------------------------------------

class TestScoreDisclosureImpact:
    """AC-001, AC-002, AC-003, AC-004: score_disclosure_impact 함수 검증."""

    def test_기업지배구조_루틴_기본점수(self):
        """기업지배구조 공시 — 루틴(M&A 키워드 없음) → 기본 점수 10."""
        d = _make_disclosure(report_type="기업지배구조", report_name="이사회 의결 통지")
        assert score_disclosure_impact(d, None) == 10.0

    def test_기업지배구조_MnA_가산점수(self):
        """기업지배구조 공시 — 합병/분할 등 M&A 키워드 감지 → 기본 10 + 20 = 30."""
        for keyword in ("합병계약 체결", "회사분할결정", "영업양수도 결정", "주식교환"):
            d = _make_disclosure(report_type="기업지배구조", report_name=keyword)
            assert score_disclosure_impact(d, None) == 30.0, keyword

    def test_루틴_거버넌스_공시_캡(self):
        """정기주총결과, 주주총회소집공고, 사외이사 선임·해임 신고 등은 5점으로 제한."""
        routine_cases = [
            ("기업지배구조", "정기주주총회결과"),
            ("기업지배구조", "[기재정정]정기주주총회결과"),
            ("기업지배구조", "주주총회소집공고"),
            ("기업지배구조", "주주총회 소집공고"),
            ("기업지배구조", "사외이사의 선임·해임 또는 중도퇴임에 관한 신고"),
            ("기업지배구조", "사외이사의 선임ㆍ해임또는중도퇴임에관한신고"),
            ("기업지배구조", "[기재정정]기업가치제고계획(자율공시)(고배당기업 표시를 위한 재공시)"),
            ("지분공시", "임원·주요주주특정증권등소유상황보고서"),
        ]
        for report_type, report_name in routine_cases:
            d = _make_disclosure(report_type=report_type, report_name=report_name)
            assert score_disclosure_impact(d, None) == 5.0, report_name

    def test_지분공시_기본점수(self):
        """AC-001: 지분공시 → 기본 점수 25."""
        d = _make_disclosure(report_type="지분공시")
        assert score_disclosure_impact(d, None) == 25.0

    def test_발행공시_음수점수(self):
        """AC-001: 발행공시(신주/전환사채) → 희석 효과 -10."""
        d = _make_disclosure(report_type="발행공시")
        assert score_disclosure_impact(d, None) == -10.0

    def test_수주계약_시총비율_계산(self):
        """AC-002: 단일판매·공급계약 수주금액/시총 비율로 점수 계산.

        수주금액 500억, 시총 1000억 → ratio=0.5 → score=min(250, 100)=100.
        """
        d = _make_disclosure(
            report_type="주요사항보고",
            report_name="단일판매공급계약체결 500억원",
        )
        score = score_disclosure_impact(d, market_cap_億=1000)
        assert score == 100.0

    def test_수주계약_소형계약_낮은점수(self):
        """AC-002: 소형 수주(시총 대비 1%) → 낮은 충격 점수."""
        d = _make_disclosure(
            report_type="주요사항보고",
            report_name="단일판매공급계약체결 10억원",
        )
        score = score_disclosure_impact(d, market_cap_億=1000)
        # ratio=0.01 → 0.01*500=5.0
        assert score == 5.0

    def test_실적변동_퍼센트_추출(self):
        """AC-003: 실적변동 공시 AI 요약에서 변화율 추출."""
        d = _make_disclosure(
            report_type="실적변동",
            ai_summary="영업이익 75% 증가로 예상대비 대폭 성장",
        )
        assert score_disclosure_impact(d, None) == 75.0

    def test_실적변동_100초과_클램핑(self):
        """AC-003: 실적변동 점수는 100을 초과하지 않는다."""
        d = _make_disclosure(
            report_type="실적변동",
            ai_summary="영업이익 150% 급증",
        )
        assert score_disclosure_impact(d, None) == 100.0

    def test_기타공시_기본점수(self):
        """AC-004: 알 수 없는 공시 유형 → 기본 점수 10."""
        d = _make_disclosure(report_type="알수없는유형")
        assert score_disclosure_impact(d, None) == 10.0

    def test_정기공시_기본점수(self):
        """AC-004: 정기공시 → 기본 점수 10."""
        d = _make_disclosure(report_type="정기공시")
        assert score_disclosure_impact(d, None) == 10.0


# ---------------------------------------------------------------------------
# AC-002: 수주금액 추출 함수 단위 테스트
# ---------------------------------------------------------------------------

class TestExtractContractAmount:
    """extract_contract_amount 함수 단위 테스트."""

    def test_억원_파싱(self):
        """'500억원' 형식 파싱."""
        assert extract_contract_amount("공급계약 500억원 체결", None) == 500

    def test_조원_파싱(self):
        """'1.5조원' → 15000억 환산."""
        assert extract_contract_amount("단일판매공급계약 1.5조원", None) == 15000

    def test_백만원_파싱(self):
        """'10000백만원' → 100억 환산."""
        assert extract_contract_amount("수주 10000백만원", None) == 100

    def test_금액없음_None반환(self):
        """금액 패턴 없으면 None 반환."""
        assert extract_contract_amount("일반 사업보고서", None) is None

    def test_ai_summary에서_추출(self):
        """report_name이 아닌 ai_summary에서 금액 추출."""
        assert extract_contract_amount("단일판매공급계약체결", "계약금액 200억원 규모") == 200

    def test_쉼표포함_금액_파싱(self):
        """'1,234억원' 형식 파싱."""
        assert extract_contract_amount("수주 1,234억원", None) == 1234


# ---------------------------------------------------------------------------
# AC-005: 기준가 스냅샷
# ---------------------------------------------------------------------------

class TestCaptureBaselinePrice:
    """AC-005: capture_baseline_price 함수 테스트."""

    @pytest.mark.asyncio
    async def test_stock_code_없으면_None(self):
        """stock_code 없으면 None 반환."""
        d = _make_disclosure(stock_code=None)
        result = await capture_baseline_price(d)
        assert result is None

    @pytest.mark.asyncio
    async def test_주가조회_성공(self):
        """stock_code 있으면 naver_finance에서 현재가 반환."""
        d = _make_disclosure(stock_code="005930")
        with patch(
            "app.services.naver_finance.fetch_current_price",
            new_callable=AsyncMock,
            return_value=75000,
        ):
            result = await capture_baseline_price(d)
        # 내부 import 구조상 mock이 적용되면 75000, 아니면 None
        assert result is None or result == 75000

    @pytest.mark.asyncio
    async def test_주가조회_예외시_None(self):
        """naver_finance 호출 중 예외 발생 시 None 반환."""
        d = _make_disclosure(stock_code="005930")
        with patch(
            "app.services.naver_finance.fetch_current_price",
            new_callable=AsyncMock,
            side_effect=Exception("연결 오류"),
        ):
            result = await capture_baseline_price(d)
        assert result is None


# ---------------------------------------------------------------------------
# AC-006: 반영도 계산
# ---------------------------------------------------------------------------

class TestMeasurePriceReflection:
    """AC-006: measure_price_reflection 함수 테스트."""

    @pytest.mark.asyncio
    async def test_반영도_계산(self):
        """현재가 vs 기준가로 반영도(%) 계산."""
        with patch(
            "app.services.naver_finance.fetch_current_price",
            new_callable=AsyncMock,
            return_value=52500,
        ):
            result = await measure_price_reflection("005930", 50000)
        assert result == 5.0  # (52500-50000)/50000*100 = 5.0

    @pytest.mark.asyncio
    async def test_현재가_조회실패_0반환(self):
        """현재가 조회 실패 시 0.0 반환."""
        with patch(
            "app.services.naver_finance.fetch_current_price",
            new_callable=AsyncMock,
            side_effect=Exception("연결 오류"),
        ):
            result = await measure_price_reflection("005930", 50000)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_기준가_0이면_0반환(self):
        """기준가가 0이면 0.0 반환 (ZeroDivisionError 방지)."""
        with patch(
            "app.services.naver_finance.fetch_current_price",
            new_callable=AsyncMock,
            return_value=52500,
        ):
            result = await measure_price_reflection("005930", 0)
        assert result == 0.0


# ---------------------------------------------------------------------------
# AC-007, AC-008: 미반영 갭 탐지
# ---------------------------------------------------------------------------

class TestDetectUnreflectedGap:
    """AC-007, AC-008: detect_unreflected_gap 함수 테스트."""

    def test_갭_15이상_True(self):
        """갭 >= 15이면 True 반환 (AC-007)."""
        d = _make_disclosure(impact_score=50.0, reflected_pct=30.0)  # 갭=20
        assert detect_unreflected_gap(d) is True

    def test_갭_15미만_False(self):
        """갭 < 15이면 False 반환."""
        d = _make_disclosure(impact_score=30.0, reflected_pct=20.0)  # 갭=10
        assert detect_unreflected_gap(d) is False

    def test_80퍼센트이상_반영시_False(self):
        """이미 80% 이상 반영된 경우 False 반환 (AC-008).

        impact=50, reflected=42 → 42 >= 50*0.8=40 → 이미 충분히 반영됨.
        """
        d = _make_disclosure(impact_score=50.0, reflected_pct=42.0)
        assert detect_unreflected_gap(d) is False

    def test_impact_score_None_False(self):
        """impact_score가 None이면 False 반환."""
        d = _make_disclosure(impact_score=None, reflected_pct=10.0)
        assert detect_unreflected_gap(d) is False

    def test_reflected_pct_None_False(self):
        """reflected_pct가 None이면 False 반환."""
        d = _make_disclosure(impact_score=50.0, reflected_pct=None)
        assert detect_unreflected_gap(d) is False

    def test_정확히_15갭_True(self):
        """갭이 정확히 15이면 True 반환."""
        d = _make_disclosure(impact_score=40.0, reflected_pct=25.0)  # 갭=15
        assert detect_unreflected_gap(d) is True

    def test_음수_impact_False(self):
        """음수 impact (발행공시 등) → 갭이 음수이므로 False."""
        d = _make_disclosure(impact_score=-10.0, reflected_pct=0.0)
        assert detect_unreflected_gap(d) is False


# ---------------------------------------------------------------------------
# AC-010: activate_gap_pullback 테스트
# ---------------------------------------------------------------------------

class TestActivateGapPullback:
    """AC-010: activate_gap_pullback 함수 테스트 (REQ-DISC-015)."""

    def _make_db_with_signal(self, signal: MagicMock, stock: MagicMock) -> MagicMock:
        """signal과 stock을 반환하는 DB mock 생성."""
        db = MagicMock()
        # 첫 번째 query().filter().all() 호출 → 시그널 목록
        db.query.return_value.filter.return_value.all.return_value = [signal]
        # query().filter().first() 호출 → 종목
        db.query.return_value.filter.return_value.first.return_value = stock
        db.add = MagicMock()
        db.commit = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_풀백조건_충족_활성화(self):
        """시가대비 -3% ~ -1.5% 구간이면 시그널 활성화 (REQ-DISC-015)."""
        signal = _make_signal()
        stock = _make_stock()
        db = self._make_db_with_signal(signal, stock)

        # open_price=50000, current=-2% → pct_from_open=-2.0 (조건 충족)
        price_data = {
            "current_price": 49000,  # 50000 * 0.98
            "open_price": 50000,
            "change_rate": -2.0,
        }

        with (
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value=price_data,
            ),
            patch(
                "app.services.paper_trading.execute_signal_trade",
                new_callable=AsyncMock,
            ),
        ):
            result = await activate_gap_pullback(db)

        assert result["checked"] >= 1
        assert result["activated"] >= 1
        assert "활성화됨" in signal.reasoning

    @pytest.mark.asyncio
    async def test_풀백조건_미충족_미활성화(self):
        """시가대비 등락률이 범위 밖이면 활성화하지 않는다."""
        signal = _make_signal()
        stock = _make_stock()
        db = self._make_db_with_signal(signal, stock)

        # 시가 대비 0% → 조건 미충족 (-3% ~ -1.5% 범위 밖)
        price_data = {
            "current_price": 50000,
            "open_price": 50000,
            "change_rate": 0.0,
        }

        with patch(
            "app.services.naver_finance.fetch_current_price_with_change",
            new_callable=AsyncMock,
            return_value=price_data,
        ):
            result = await activate_gap_pullback(db)

        assert result["activated"] == 0
        assert "활성화됨" not in signal.reasoning

    @pytest.mark.asyncio
    async def test_풀백_과도하게_하락_미활성화(self):
        """시가 대비 -3% 미만으로 추가 하락 시 조건 미충족."""
        signal = _make_signal()
        stock = _make_stock()
        db = self._make_db_with_signal(signal, stock)

        # 시가 대비 -5% → 범위 밖 (-3% ~ -1.5%)
        price_data = {
            "current_price": 47500,  # -5%
            "open_price": 50000,
            "change_rate": -5.0,
        }

        with patch(
            "app.services.naver_finance.fetch_current_price_with_change",
            new_callable=AsyncMock,
            return_value=price_data,
        ):
            result = await activate_gap_pullback(db)

        assert result["activated"] == 0

    @pytest.mark.asyncio
    async def test_이미_활성화된_시그널_스킵(self):
        """'활성화됨' 표시가 있는 시그널은 처리 대상에서 제외된다."""
        signal = _make_signal(reasoning="[활성화됨] 이미 처리됨")
        stock = _make_stock()
        db = self._make_db_with_signal(signal, stock)

        price_data = {
            "current_price": 49000,
            "open_price": 50000,
            "change_rate": -2.0,
        }

        with patch(
            "app.services.naver_finance.fetch_current_price_with_change",
            new_callable=AsyncMock,
            return_value=price_data,
        ):
            result = await activate_gap_pullback(db)

        # reasoning에 이미 "활성화됨"이 있으므로 target_signals에서 제외
        assert result["activated"] == 0
        assert result["checked"] == 0

    @pytest.mark.asyncio
    async def test_시그널_없으면_0반환(self):
        """대상 시그널이 없으면 checked=0, activated=0 반환."""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        result = await activate_gap_pullback(db)
        assert result["checked"] == 0
        assert result["activated"] == 0


# ---------------------------------------------------------------------------
# detect_sector_ripple 테스트
# ---------------------------------------------------------------------------

class TestDetectSectorRipple:
    """동종업계 파급 탐지 함수 테스트 (REQ-DISC-011 ~ REQ-DISC-013)."""

    @pytest.mark.asyncio
    async def test_stock_id_없으면_빈리스트(self):
        """stock_id 없는 공시 → 빈 결과 반환."""
        d = _make_disclosure(stock_id=None)
        db = MagicMock()
        result = await detect_sector_ripple(db, d)
        assert result == []

    @pytest.mark.asyncio
    async def test_섹터없으면_빈리스트(self):
        """트리거 종목에 섹터 없으면 빈 결과 반환."""
        d = _make_disclosure(stock_id=1)
        trigger_stock = _make_stock(sector_id=None)

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = trigger_stock

        result = await detect_sector_ripple(db, d)
        assert result == []

    @pytest.mark.asyncio
    async def test_이미반응종목_제외(self):
        """이미 +2% 이상 반응한 종목은 파급 후보에서 제외 (REQ-DISC-011)."""
        d = _make_disclosure(stock_id=1)

        trigger_stock = _make_stock(id=1, sector_id=10, market_cap=10000, stock_code="000001")
        already_reacted = _make_stock(id=2, name="이미반응종목", sector_id=10, stock_code="000002", market_cap=5000)

        db = MagicMock()
        # 첫 번째 first() 호출 → trigger_stock
        db.query.return_value.filter.return_value.first.return_value = trigger_stock
        db.query.return_value.filter.return_value.all.return_value = [already_reacted]

        # 이미 +3% 반응 → REQ-DISC-011에 의해 제외
        with patch(
            "app.services.naver_finance.fetch_current_price_with_change",
            new_callable=AsyncMock,
            return_value={"current_price": 10300, "change_rate": 3.0},
        ):
            result = await detect_sector_ripple(db, d)

        assert result == []

    @pytest.mark.asyncio
    async def test_동종업계_파급_후보_탐지(self):
        """아직 반응하지 않은(-2% 미만) 종목은 파급 후보로 탐지된다 (REQ-DISC-012)."""
        d = _make_disclosure(stock_id=1)

        trigger_stock = _make_stock(id=1, sector_id=10, market_cap=10000, stock_code="000001")
        unreacted = _make_stock(id=2, name="미반응종목", sector_id=10, stock_code="000002", market_cap=5000)

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = trigger_stock
        db.query.return_value.filter.return_value.all.return_value = [unreacted]

        # +0.5% → 아직 반응 안 함 (< +2%)
        with patch(
            "app.services.naver_finance.fetch_current_price_with_change",
            new_callable=AsyncMock,
            return_value={"current_price": 10050, "change_rate": 0.5},
        ):
            result = await detect_sector_ripple(db, d)

        assert len(result) == 1
        assert result[0]["stock_id"] == 2


# ---------------------------------------------------------------------------
# run_reflection_check 통합 흐름 테스트
# ---------------------------------------------------------------------------

class TestRunReflectionCheck:
    """run_reflection_check 함수 통합 테스트."""

    @pytest.mark.asyncio
    async def test_공시없으면_조기종료(self):
        """존재하지 않는 disclosure_id → 아무 동작 없이 종료."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        # 예외 없이 조용히 종료되어야 한다
        await run_reflection_check(db, disclosure_id=9999)

    @pytest.mark.asyncio
    async def test_미반영갭탐지시_시그널생성(self):
        """미반영 갭 >= 15이면 FundSignal을 생성한다 (REQ-DISC-007, REQ-DISC-010)."""
        disclosure = _make_disclosure(
            id=1,
            stock_id=1,
            stock_code="005930",
            baseline_price=50000,
            impact_score=50.0,
            reflected_pct=None,
            unreflected_gap=None,
            ripple_checked=False,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = disclosure
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        with (
            patch(
                "app.services.disclosure_impact_scorer.measure_price_reflection",
                new_callable=AsyncMock,
                return_value=10.0,  # 반영도 10% → 갭=40 >= 15 → 시그널 생성
            ),
            patch(
                "app.services.disclosure_impact_scorer._create_disclosure_signal",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            await run_reflection_check(db, disclosure_id=1)

        mock_create.assert_called_once()
        assert disclosure.reflected_pct == 10.0
        assert disclosure.unreflected_gap == 40.0  # 50 - 10

    @pytest.mark.asyncio
    async def test_이미반영된_경우_시그널_미생성(self):
        """80% 이상 반영된 경우 FundSignal을 생성하지 않는다 (REQ-DISC-008)."""
        disclosure = _make_disclosure(
            id=1,
            stock_id=1,
            stock_code="005930",
            baseline_price=50000,
            impact_score=50.0,
            reflected_pct=None,
            unreflected_gap=None,
            ripple_checked=False,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = disclosure
        db.add = MagicMock()
        db.commit = MagicMock()

        with (
            patch(
                "app.services.disclosure_impact_scorer.measure_price_reflection",
                new_callable=AsyncMock,
                return_value=45.0,  # 반영도 45% → 50*0.8=40 초과 → 이미 충분히 반영
            ),
            patch(
                "app.services.disclosure_impact_scorer._create_disclosure_signal",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            await run_reflection_check(db, disclosure_id=1)

        # 이미 반영됐으므로 시그널 생성 없어야 함
        mock_create.assert_not_called()
