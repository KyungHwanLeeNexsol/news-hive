"""SPEC-AI-068 REQ-001: 유니버스 멤버 영속화 서비스 테스트.

persist_universe_members / get_universe_members_for_date의 일자당 replace semantics,
빈 유니버스, 스테일 코드 제거(EC-5), entry_pool 태깅을 검증한다.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.surge_universe_member import SurgeUniverseMember
from app.services.surge_universe_pool_service import (
    get_universe_members_for_date,
    persist_universe_members,
)


class TestPersistUniverseMembers:
    def test_persist_basic_members_with_pool_tags(self, db: Session):
        """Scenario 2: Pool A={A}, B={B,C}, C={D} → 종목코드+풀 태그가 영속화된다."""
        trading_date = date(2026, 6, 30)
        universe_codes = ["A", "B", "C", "D"]
        entry_pool_map = {"A": "pool_a", "B": "pool_b", "C": "pool_b", "D": "pool_c"}

        saved_count = persist_universe_members(db, trading_date, universe_codes, entry_pool_map)
        db.commit()

        assert saved_count == 4

        members = get_universe_members_for_date(db, trading_date)
        assert members == {"A", "B", "C", "D"}

        rows = (
            db.query(SurgeUniverseMember)
            .filter(SurgeUniverseMember.trading_date == trading_date)
            .all()
        )
        pool_by_code = {r.stock_code: r.entry_pool for r in rows}
        assert pool_by_code == {
            "A": "pool_a",
            "B": "pool_b",
            "C": "pool_b",
            "D": "pool_c",
        }

    def test_persist_defaults_to_existing_pool_when_unmapped(self, db: Session):
        """entry_pool_map에 없는 코드는 'existing'으로 태깅된다."""
        trading_date = date(2026, 6, 30)
        persist_universe_members(db, trading_date, ["E"], {})
        db.commit()

        row = (
            db.query(SurgeUniverseMember)
            .filter(
                SurgeUniverseMember.trading_date == trading_date,
                SurgeUniverseMember.stock_code == "E",
            )
            .first()
        )
        assert row is not None
        assert row.entry_pool == "existing"

    def test_persist_empty_universe_returns_zero_and_no_rows(self, db: Session):
        """빈 유니버스 리스트를 넘기면 저장 0건, 조회 시 빈 집합."""
        trading_date = date(2026, 6, 30)
        saved_count = persist_universe_members(db, trading_date, [], {})
        db.commit()

        assert saved_count == 0
        assert get_universe_members_for_date(db, trading_date) == set()

    def test_persist_deduplicates_codes(self, db: Session):
        """universe_codes에 중복 코드가 있어도 1건만 저장된다."""
        trading_date = date(2026, 6, 30)
        saved_count = persist_universe_members(
            db, trading_date, ["A", "A", "B"], {"A": "pool_a", "B": "pool_b"}
        )
        db.commit()

        assert saved_count == 2
        assert get_universe_members_for_date(db, trading_date) == {"A", "B"}


class TestDailyReplaceSemantics:
    """EC-5: 동일 날짜 재실행 시 유니버스 멤버가 replace(스테일 코드 제거)된다."""

    def test_rerun_same_date_removes_stale_codes(self, db: Session):
        """1차 실행 {A,B,C,D} → 2차 축소 실행 {A,B} 시 C,D는 제거되어야 한다."""
        trading_date = date(2026, 6, 30)

        # 1차: 10:00 KST 실행 — 넓은 유니버스
        persist_universe_members(
            db,
            trading_date,
            ["A", "B", "C", "D"],
            {"A": "pool_a", "B": "pool_b", "C": "pool_b", "D": "pool_c"},
        )
        db.commit()
        assert get_universe_members_for_date(db, trading_date) == {"A", "B", "C", "D"}

        # 2차: 15:20 KST 재실행 — 축소된 유니버스 (C, D 탈락)
        saved_count = persist_universe_members(
            db, trading_date, ["A", "B"], {"A": "pool_a", "B": "pool_b"}
        )
        db.commit()

        assert saved_count == 2
        members = get_universe_members_for_date(db, trading_date)
        assert members == {"A", "B"}, "스테일 코드 C, D가 replace로 제거되어야 한다 (EC-5)"

    def test_rerun_same_date_updates_entry_pool_tag(self, db: Session):
        """동일 종목이 재실행 시 다른 풀로 재태깅되면 최신 값으로 갱신된다."""
        trading_date = date(2026, 6, 30)

        persist_universe_members(db, trading_date, ["A"], {"A": "pool_c"})
        db.commit()

        persist_universe_members(db, trading_date, ["A"], {"A": "pool_a"})
        db.commit()

        row = (
            db.query(SurgeUniverseMember)
            .filter(
                SurgeUniverseMember.trading_date == trading_date,
                SurgeUniverseMember.stock_code == "A",
            )
            .first()
        )
        assert row is not None
        assert row.entry_pool == "pool_a"

    def test_rerun_does_not_affect_other_dates(self, db: Session):
        """특정 날짜 replace가 다른 날짜의 영속화된 유니버스에 영향을 주지 않는다."""
        day1 = date(2026, 6, 29)
        day2 = date(2026, 6, 30)

        persist_universe_members(db, day1, ["X"], {"X": "pool_a"})
        db.commit()
        persist_universe_members(db, day2, ["Y"], {"Y": "pool_b"})
        db.commit()

        # day2 재실행 (day1에는 영향 없어야 함)
        persist_universe_members(db, day2, ["Z"], {"Z": "pool_c"})
        db.commit()

        assert get_universe_members_for_date(db, day1) == {"X"}
        assert get_universe_members_for_date(db, day2) == {"Z"}


class TestGetUniverseMembersForDate:
    def test_no_records_returns_empty_set(self, db: Session):
        """레코드가 없는 날짜(과거 미백필 등)는 빈 집합을 반환한다 (EC-2 전제)."""
        assert get_universe_members_for_date(db, date(1999, 1, 1)) == set()
