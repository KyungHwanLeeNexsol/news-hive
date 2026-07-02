"""SPEC-AI-068 REQ-001: 거래일별 스캔 유니버스 종목코드 영속화 모델.

build_scan_universe()가 확정한 유니버스 종목코드를 진입 풀 태그(A/B/C/existing)와 함께
거래일 키로 저장한다. 사후에 Scannable Recall/Coverage(REQ-002/003) 계산의 기준 집합으로
쓰인다. build_scan_universe 자체의 우선순위/상한 로직(SPEC-AI-065 소유)은 변경하지 않는다.
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeUniverseMember(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-068 REQ-001 — 거래일별 스캔 유니버스 종목코드 영속화.
    # composite PK (trading_date, stock_code), 일자당 replace(DELETE-then-insert) semantics
    # (동일 날짜 재실행 시 축소된 유니버스의 스테일 코드가 남지 않도록 upsert 대신 replace 사용).
    # @MX:SPEC: SPEC-AI-068 REQ-AI068-001
    """거래일별 스캔 유니버스 멤버 테이블.

    persist_universe_members()가 gather_surge_candidates() 내부(build_scan_universe 호출 직후)
    에서 기존 persist_pool_counts와 동일 트랜잭션으로 기록한다.
    get_universe_members_for_date()가 평가 잡(evaluate_surge_predictions)에서 T-1 유니버스를
    조회하여 Scannable Recall/Coverage 분모/분자 계산에 사용한다.
    """

    __tablename__ = "surge_universe_members"

    # composite PK: (trading_date, stock_code)
    trading_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False)

    # pool_a / pool_b / pool_c / existing
    entry_pool: Mapped[str] = mapped_column(String(10), nullable=False)

    # 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
