"""SPEC-AI-065 REQ-5: 스캔 유니버스 pool 집계 히스토리 모델.

gather_surge_candidates()가 라이브 시그널 생성(10:00/15:20 KST) 중 계산한
Pool A/B/C 종목 수와 최종 스캔 유니버스 크기를 날짜별로 저장한다.
date 컬럼은 UNIQUE 제약으로 일자당 단일 레코드를 보장한다 (동일 날짜 재실행 시 갱신).
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeUniversePoolHistory(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-065 REQ-5 — 날짜별 스캔 유니버스 pool 집계 이력.
    # date UNIQUE 제약으로 upsert 패턴 적용 (surge_threshold_history와 동일 관례)
    # @MX:SPEC: SPEC-AI-065 REQ-5
    """날짜별 스캔 유니버스 pool_a/b/c 집계 테이블.

    _run_surge_verify_predictions(18:30 KST)가 T-1 날짜의 레코드를 조회하여
    evaluate_surge_predictions()의 pool_counts 인자로 전달한다.
    """

    __tablename__ = "surge_universe_pool_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 날짜 (KST 기준, UNIQUE — 일자당 하나의 레코드만 허용)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    # Pool A (DART 공시 당일) 종목 수
    pool_a_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Pool B (거래량 200%+ 당일) 종목 수
    pool_b_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Pool C (등락률 5%+ 당일) 종목 수
    pool_c_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 최종 스캔 유니버스 크기 (max_scan_universe로 잘라낸 이후)
    scan_universe_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 레코드 생성/갱신 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
