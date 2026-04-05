"""WebSocket ConnectionManager, 이벤트 버스, WebSocket 엔드포인트 테스트."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.event_bus import (
    broadcast_event,
    clear_event_bus,
    fire_event,
    get_event_bus,
    set_event_bus,
)
from app.websocket import ConnectionManager


# ---------------------------------------------------------------------------
# ConnectionManager 단위 테스트
# ---------------------------------------------------------------------------


class TestConnectionManager:
    """ConnectionManager 핵심 기능 테스트."""

    def setup_method(self) -> None:
        self.manager = ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_registers_topics(self) -> None:
        """연결 시 지정된 토픽에 등록된다."""
        ws = AsyncMock()
        await self.manager.connect(ws, ["alerts", "signals"])

        assert ws in self.manager.active_connections.get("alerts", [])
        assert ws in self.manager.active_connections.get("signals", [])
        assert ws not in self.manager.active_connections.get("news", [])

    @pytest.mark.asyncio
    async def test_connect_ignores_invalid_topics(self) -> None:
        """유효하지 않은 토픽은 무시된다."""
        ws = AsyncMock()
        await self.manager.connect(ws, ["alerts", "invalid_topic", "xyz"])

        assert "alerts" in self.manager.active_connections
        assert "invalid_topic" not in self.manager.active_connections
        assert "xyz" not in self.manager.active_connections

    @pytest.mark.asyncio
    async def test_connect_calls_accept(self) -> None:
        """connect 시 websocket.accept()가 호출된다."""
        ws = AsyncMock()
        await self.manager.connect(ws, ["alerts"])
        ws.accept.assert_awaited_once()

    def test_disconnect_removes_from_all_topics(self) -> None:
        """disconnect 시 모든 토픽에서 제거된다."""
        ws = MagicMock()
        self.manager.active_connections["alerts"] = [ws]
        self.manager.active_connections["signals"] = [ws]

        self.manager.disconnect(ws)

        assert ws not in self.manager.active_connections.get("alerts", [])
        assert ws not in self.manager.active_connections.get("signals", [])

    def test_disconnect_cleans_empty_topics(self) -> None:
        """연결이 없는 토픽은 딕셔너리에서 제거된다."""
        ws = MagicMock()
        self.manager.active_connections["alerts"] = [ws]

        self.manager.disconnect(ws)

        assert "alerts" not in self.manager.active_connections

    def test_disconnect_keeps_other_connections(self) -> None:
        """다른 클라이언트의 연결은 유지된다."""
        ws1 = MagicMock()
        ws2 = MagicMock()
        self.manager.active_connections["alerts"] = [ws1, ws2]

        self.manager.disconnect(ws1)

        assert ws2 in self.manager.active_connections["alerts"]
        assert ws1 not in self.manager.active_connections["alerts"]

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_topic_subscribers(self) -> None:
        """브로드캐스트는 해당 토픽 구독자에게만 전송된다."""
        ws_alerts = AsyncMock()
        ws_news = AsyncMock()

        await self.manager.connect(ws_alerts, ["alerts"])
        await self.manager.connect(ws_news, ["news"])

        await self.manager.broadcast("alerts", {"level": "critical"})

        # alerts 구독자에게 전송됨
        ws_alerts.send_text.assert_awaited_once()
        sent_data = json.loads(ws_alerts.send_text.call_args[0][0])
        assert sent_data["type"] == "alerts"
        assert sent_data["data"]["level"] == "critical"

        # news 구독자에게는 전송되지 않음
        ws_news.send_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_broadcast_empty_topic_no_error(self) -> None:
        """구독자가 없는 토픽에 브로드캐스트해도 에러가 발생하지 않는다."""
        await self.manager.broadcast("nonexistent", {"test": True})
        # 예외 없이 정상 종료

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self) -> None:
        """전송 실패한 연결은 자동으로 제거된다."""
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = RuntimeError("connection closed")

        await self.manager.connect(ws_alive, ["alerts"])
        await self.manager.connect(ws_dead, ["alerts"])

        await self.manager.broadcast("alerts", {"test": True})

        # 살아있는 연결은 유지
        assert ws_alive in self.manager.active_connections.get("alerts", [])
        # 죽은 연결은 제거
        assert ws_dead not in self.manager.active_connections.get("alerts", [])

    @pytest.mark.asyncio
    async def test_broadcast_continues_after_failure(self) -> None:
        """한 클라이언트 실패 후에도 나머지에게 전송한다."""
        ws1 = AsyncMock()
        ws1.send_text.side_effect = RuntimeError("broken")
        ws2 = AsyncMock()
        ws3 = AsyncMock()

        await self.manager.connect(ws1, ["signals"])
        await self.manager.connect(ws2, ["signals"])
        await self.manager.connect(ws3, ["signals"])

        await self.manager.broadcast("signals", {"signal": "buy"})

        ws2.send_text.assert_awaited_once()
        ws3.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_count(self) -> None:
        """connection_count는 중복 제외한 고유 연결 수를 반환한다."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        assert self.manager.connection_count == 0

        await self.manager.connect(ws1, ["alerts", "signals"])
        assert self.manager.connection_count == 1  # 같은 ws가 2개 토픽에 등록되어도 1

        await self.manager.connect(ws2, ["alerts"])
        assert self.manager.connection_count == 2

    @pytest.mark.asyncio
    async def test_topic_counts(self) -> None:
        """topic_counts는 토픽별 구독자 수를 반환한다."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await self.manager.connect(ws1, ["alerts", "news"])
        await self.manager.connect(ws2, ["alerts"])

        counts = self.manager.topic_counts
        assert counts["alerts"] == 2
        assert counts["news"] == 1


# ---------------------------------------------------------------------------
# 이벤트 버스 테스트
# ---------------------------------------------------------------------------


class TestEventBus:
    """event_bus 모듈 테스트."""

    def setup_method(self) -> None:
        clear_event_bus()

    def teardown_method(self) -> None:
        clear_event_bus()

    def test_set_and_get_event_bus(self) -> None:
        """set_event_bus/get_event_bus 기본 동작."""
        assert get_event_bus() is None

        mgr = ConnectionManager()
        set_event_bus(mgr)
        assert get_event_bus() is mgr

    def test_clear_event_bus(self) -> None:
        """clear_event_bus 후 get_event_bus는 None을 반환한다."""
        set_event_bus(ConnectionManager())
        clear_event_bus()
        assert get_event_bus() is None

    @pytest.mark.asyncio
    async def test_broadcast_event_without_bus(self) -> None:
        """이벤트 버스가 없으면 broadcast_event는 조용히 무시한다."""
        # 예외 없이 정상 반환
        await broadcast_event("alerts", {"test": True})

    @pytest.mark.asyncio
    async def test_broadcast_event_with_bus(self) -> None:
        """이벤트 버스가 등록되면 broadcast를 호출한다."""
        mgr = ConnectionManager()
        mgr.broadcast = AsyncMock()
        set_event_bus(mgr)

        await broadcast_event("alerts", {"level": "warning"})
        mgr.broadcast.assert_awaited_once_with("alerts", {"level": "warning"})

    @pytest.mark.asyncio
    async def test_broadcast_event_handles_exception(self) -> None:
        """broadcast 중 예외가 발생해도 broadcast_event는 에러를 삼킨다."""
        mgr = ConnectionManager()
        mgr.broadcast = AsyncMock(side_effect=RuntimeError("boom"))
        set_event_bus(mgr)

        # 예외 없이 정상 반환
        await broadcast_event("alerts", {"test": True})

    def test_fire_event_without_bus(self) -> None:
        """이벤트 버스가 없으면 fire_event는 조용히 무시한다."""
        fire_event("alerts", {"test": True})
        # 예외 없이 정상 종료


# ---------------------------------------------------------------------------
# WebSocket 엔드포인트 통합 테스트
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    """FastAPI WebSocket 엔드포인트 통합 테스트."""

    def _get_test_client(self):
        """테스트용 클라이언트 생성 (lifespan 비활성화)."""
        from unittest.mock import patch as _patch
        from fastapi.testclient import TestClient
        from app.main import app
        from app import websocket as ws_module

        # ConnectionManager 설정
        mgr = ConnectionManager()
        ws_module.manager = mgr

        with (
            _patch("app.main._run_migrations"),
            _patch("app.main.start_scheduler"),
            _patch("app.main.stop_scheduler"),
            _patch("threading.Thread"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
        return client, mgr

    def test_websocket_connect_and_ping_pong(self) -> None:
        """WebSocket 연결 후 ping/pong 동작을 확인한다."""
        client, mgr = self._get_test_client()

        with client.websocket_connect("/ws?topics=alerts") as ws:
            # ping 전송
            ws.send_text(json.dumps({"type": "ping"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "pong"

    def test_websocket_receives_broadcast(self) -> None:
        """WebSocket 클라이언트가 브로드캐스트 메시지를 수신한다."""
        client, mgr = self._get_test_client()

        with client.websocket_connect("/ws?topics=alerts") as ws:
            # 별도 스레드에서 브로드캐스트 실행
            import threading

            def _broadcast():
                asyncio.run(mgr.broadcast("alerts", {"level": "critical", "title": "테스트"}))

            t = threading.Thread(target=_broadcast)
            t.start()
            t.join(timeout=3)

            msg = json.loads(ws.receive_text())
            assert msg["type"] == "alerts"
            assert msg["data"]["level"] == "critical"

    def test_websocket_default_topics(self) -> None:
        """토픽 없이 연결하면 기본 토픽(alerts,signals,news)이 적용된다."""
        client, mgr = self._get_test_client()

        with client.websocket_connect("/ws") as ws:
            # 기본 토픽 3개에 연결됨
            assert mgr.connection_count == 1
            assert "alerts" in mgr.active_connections
            assert "signals" in mgr.active_connections
            assert "news" in mgr.active_connections

    def test_websocket_invalid_message_ignored(self) -> None:
        """잘못된 JSON 메시지를 보내도 연결이 끊어지지 않는다."""
        client, mgr = self._get_test_client()

        with client.websocket_connect("/ws?topics=alerts") as ws:
            ws.send_text("not-json-at-all")
            # 연결이 유지되는지 확인 -- ping으로 검증
            ws.send_text(json.dumps({"type": "ping"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "pong"
