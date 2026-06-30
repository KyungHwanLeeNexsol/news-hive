"""SPEC-AI-038: BEAR threshold cap, volume threshold 완화, 장중 재탐지 인수 검증 테스트.

미해결 항목 3가지:
  REQ-038-001 volume_zscore_threshold 완화 (default 2.0, BEAR 2.5)
  REQ-038-002 BEAR regime threshold 상한 설정 (multiplier 1.05, clamp_max 0.65)
  REQ-038-003 10:00 KST 장중 재탐지 잡 등록
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from app.surge_config.surge_settings import get_surge_config
from app.services.surge_threshold_service import compute_adaptive_threshold


# ---------------------------------------------------------------------------
# REQ-038-001: volume_zscore_threshold 완화
# ---------------------------------------------------------------------------

class TestVolumeZscoreThreshold:
    """AC-038-001: volume_zscore_threshold 설정값 검증."""

    def test_default_threshold_is_2_0(self) -> None:
        """기본 volume_zscore_threshold가 2.0이어야 한다."""
        cfg = get_surge_config()
        assert cfg.volume_news_combo.volume_zscore_threshold == 2.0, (
            f"기본값 2.0 기대, 실제: {cfg.volume_news_combo.volume_zscore_threshold}"
        )

    def test_bear_regime_threshold_is_2_0(self) -> None:
        """BEAR regime volume_zscore_threshold가 2.0이어야 한다 (P2 fix 2026-06-30: 2.5→2.0)."""
        cfg = get_surge_config()
        bear_params = cfg.regime_detector_params.get("BEAR")
        assert bear_params is not None, "BEAR regime_detector_params 없음"
        assert bear_params.volume_zscore_threshold == 2.0, (
            f"BEAR threshold 2.0 기대, 실제: {bear_params.volume_zscore_threshold}"
        )

    def test_bull_regime_threshold_is_2_0(self) -> None:
        """BULL regime volume_zscore_threshold가 2.0으로 유지되어야 한다."""
        cfg = get_surge_config()
        bull_params = cfg.regime_detector_params.get("BULL")
        assert bull_params is not None, "BULL regime_detector_params 없음"
        assert bull_params.volume_zscore_threshold == 2.0


# ---------------------------------------------------------------------------
# REQ-038-002: BEAR regime threshold 상한 설정
# ---------------------------------------------------------------------------

class TestBearThresholdCap:
    """AC-038-002: BEAR regime에서 임계값이 final_clamp_max(0.65)를 초과하지 않아야 한다."""

    def test_bear_multiplier_is_1_00(self) -> None:
        """BEAR regime_multiplier가 1.00이어야 한다.
        2026-06-05: 1.05→1.00 — 탐지 임계값(0.42)이 이미 낮아지므로 추가 배율 불필요.
        """
        cfg = get_surge_config()
        bear_mult = cfg.adaptive_threshold.regime_multipliers.get("BEAR", 1.0)
        assert bear_mult == 1.00, f"BEAR multiplier 1.00 기대, 실제: {bear_mult}"

    def test_final_clamp_max_is_0_55(self) -> None:
        """final_clamp_max가 0.55이어야 한다.
        2026-06-05: 0.65→0.55 — 어떤 조건에서도 임계값 0.55 이하로 제한.
        """
        cfg = get_surge_config()
        assert cfg.adaptive_threshold.final_clamp_max == 0.55, (
            f"clamp_max 0.55 기대, 실제: {cfg.adaptive_threshold.final_clamp_max}"
        )

    def test_bear_threshold_capped_at_0_55(self) -> None:
        """BEAR regime + 저승률 조건에서도 threshold가 0.55를 초과하지 않아야 한다.
        2026-06-05: final_clamp_max 0.65→0.55.
        """
        cfg = get_surge_config()

        with patch("app.services.surge_threshold_service._get_recent_closed_trades") as mock_trades, \
             patch("app.services.surge_threshold_service.get_or_create_today_regime") as mock_regime:
            # 최악 조건: win_rate_window 만큼 패배 (win_rate=0.0)
            mock_trades.return_value = [
                MagicMock(exit_reason="stop_loss") for _ in range(cfg.adaptive_threshold.win_rate_window)
            ]
            # BEAR regime
            regime_obj = MagicMock()
            regime_obj.regime.value = "BEAR"
            mock_regime.return_value = regime_obj

            db = MagicMock()
            threshold = compute_adaptive_threshold(db, cfg)

        assert threshold <= 0.55, (
            f"BEAR + 저승률에서 threshold가 0.55 초과: {threshold:.3f}"
        )

    def test_bear_threshold_lower_than_before(self) -> None:
        """BEAR 조건에서 기존(1.2 multiplier, 0.85 clamp)보다 threshold가 낮아야 한다."""
        import copy
        # 구버전 설정으로 계산 (싱글턴 오염 방지: deepcopy 사용)
        old_cfg = copy.deepcopy(get_surge_config())
        old_cfg.adaptive_threshold.regime_multipliers["BEAR"] = 1.2
        old_cfg.adaptive_threshold.final_clamp_max = 0.85

        # 신버전 설정으로 계산 (원본 싱글턴)
        new_cfg = get_surge_config()

        with patch("app.services.surge_threshold_service._get_recent_closed_trades") as mock_trades, \
             patch("app.services.surge_threshold_service.get_or_create_today_regime") as mock_regime:
            mock_trades.return_value = [
                MagicMock(exit_reason="stop_loss") for _ in range(5)
            ]
            regime_obj = MagicMock()
            regime_obj.regime.value = "BEAR"
            mock_regime.return_value = regime_obj

            db = MagicMock()
            old_threshold = compute_adaptive_threshold(db, old_cfg)
            new_threshold = compute_adaptive_threshold(db, new_cfg)

        assert new_threshold <= old_threshold, (
            f"신규 threshold({new_threshold:.3f})가 구버전({old_threshold:.3f})보다 높음"
        )


# ---------------------------------------------------------------------------
# REQ-038-003: 10:00 KST 장중 재탐지 잡 등록
# ---------------------------------------------------------------------------

class TestIntradaySchedulerJob:
    """AC-038-003: 10:00 KST 장중 재탐지 잡이 등록되어야 한다."""

    def test_intraday_job_exists_in_start_scheduler(self) -> None:
        """start_scheduler() 호출 시 surge_signal_generate_intraday 잡이 등록되어야 한다."""
        from unittest.mock import patch, MagicMock

        added_jobs: list[dict] = []

        def fake_add_job(func, trigger, **kwargs) -> None:
            added_jobs.append({"id": kwargs.get("id"), "hour": kwargs.get("hour"),
                               "minute": kwargs.get("minute")})

        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = fake_add_job
        mock_scheduler.running = False

        with patch("app.services.scheduler.scheduler", mock_scheduler), \
             patch("app.services.scheduler.SessionLocal"), \
             patch("app.services.scheduler._run_sector_momentum"), \
             patch("app.services.scheduler.asyncio.run"):
            from app.services.scheduler import start_scheduler
            try:
                start_scheduler()
            except Exception:
                pass  # 잡 등록 이후 예외 무시

        intraday_job_ids = [j["id"] for j in added_jobs if j.get("id") == "surge_signal_generate_intraday"]
        assert len(intraday_job_ids) >= 1, (
            f"surge_signal_generate_intraday 잡 미등록. 등록된 잡: {[j['id'] for j in added_jobs]}"
        )

    def test_intraday_job_runs_at_10_00(self) -> None:
        """장중 재탐지 잡이 10:00에 설정되어야 한다."""
        from unittest.mock import patch, MagicMock

        job_kwargs: list[dict] = []

        def fake_add_job(func, trigger, **kwargs) -> None:
            if kwargs.get("id") == "surge_signal_generate_intraday":
                job_kwargs.append(kwargs)

        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = fake_add_job
        mock_scheduler.running = False

        with patch("app.services.scheduler.scheduler", mock_scheduler), \
             patch("app.services.scheduler.SessionLocal"), \
             patch("app.services.scheduler.asyncio.run"):
            from app.services.scheduler import start_scheduler
            try:
                start_scheduler()
            except Exception:
                pass

        assert len(job_kwargs) >= 1, "surge_signal_generate_intraday 잡 미발견"
        kw = job_kwargs[0]
        assert kw.get("hour") == 10, f"hour 10 기대, 실제: {kw.get('hour')}"
        assert kw.get("minute") == 0, f"minute 0 기대, 실제: {kw.get('minute')}"
