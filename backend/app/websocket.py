"""WebSocket 연결 관리자 및 엔드포인트.

토픽 기반 구독 시스템:
- alerts: 매크로 리스크 알림
- signals: AI 펀드매니저 시그널
- news: 새 뉴스 기사 알림
- prices: 가격 업데이트 (향후 확장)

JSON 메시지 프로토콜:
  수신: {"type": "ping"} -- keepalive
  발신: {"type": "alert"|"signal"|"news"|"price", "data": {...}}
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """토픽 기반 WebSocket 연결 관리자.

    각 클라이언트는 연결 시 관심 토픽을 지정하고,
    해당 토픽으로 브로드캐스트된 메시지만 수신한다.
    """

    # 허용된 토픽 목록
    VALID_TOPICS = {"alerts", "signals", "news", "prices"}

    def __init__(self) -> None:
        # topic -> WebSocket 연결 리스트
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, topics: list[str]) -> None:
        """WebSocket 연결을 수락하고 지정된 토픽에 등록한다."""
        await websocket.accept()
        for topic in topics:
            if topic in self.VALID_TOPICS:
                if topic not in self.active_connections:
                    self.active_connections[topic] = []
                self.active_connections[topic].append(websocket)
        logger.info(
            "WebSocket 연결: topics=%s (총 연결: %d)",
            topics,
            self.connection_count,
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """WebSocket 연결을 모든 토픽에서 제거한다."""
        removed_topics = []
        for topic, connections in self.active_connections.items():
            if websocket in connections:
                connections.remove(websocket)
                removed_topics.append(topic)
        # 빈 토픽 리스트 정리
        for topic in list(self.active_connections.keys()):
            if not self.active_connections[topic]:
                del self.active_connections[topic]
        if removed_topics:
            logger.info(
                "WebSocket 연결 해제: topics=%s (총 연결: %d)",
                removed_topics,
                self.connection_count,
            )

    async def broadcast(self, topic: str, data: dict) -> None:
        """특정 토픽을 구독하는 모든 클라이언트에게 메시지를 전송한다.

        개별 클라이언트 전송 실패 시 해당 연결만 제거하고 나머지는 계속 전송한다.
        """
        connections = self.active_connections.get(topic, [])
        if not connections:
            return

        message = json.dumps({"type": topic, "data": data}, ensure_ascii=False, default=str)
        dead_connections: list[WebSocket] = []

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)
                logger.debug("WebSocket 전송 실패 -- 연결 제거: topic=%s", topic)

        # 죽은 연결 제거
        for ws in dead_connections:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        """현재 활성 연결 수 (중복 제외)."""
        unique = set()
        for connections in self.active_connections.values():
            for ws in connections:
                unique.add(id(ws))
        return len(unique)

    @property
    def topic_counts(self) -> dict[str, int]:
        """토픽별 구독자 수."""
        return {topic: len(conns) for topic, conns in self.active_connections.items()}


# 모듈 레벨 매니저 인스턴스 (main.py에서 초기화)
manager: Optional[ConnectionManager] = None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    topics: str = Query(default="alerts,signals,news"),
    token: Optional[str] = Query(default=None),
) -> None:
    """WebSocket 엔드포인트.

    쿼리 파라미터:
    - topics: 쉼표로 구분된 구독 토픽 (예: "alerts,signals,news")
    - token: 관리자 전용 기능을 위한 선택적 토큰 (현재 미사용)
    """
    if manager is None:
        await websocket.close(code=1013, reason="서버 초기화 중")
        return

    # 토픽 파싱 및 유효성 검증
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    valid_topics = [t for t in topic_list if t in ConnectionManager.VALID_TOPICS]

    if not valid_topics:
        valid_topics = ["alerts", "signals", "news"]  # 기본 토픽

    await manager.connect(websocket, valid_topics)
    try:
        while True:
            # 클라이언트 메시지 수신 (keepalive ping 처리)
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except (json.JSONDecodeError, TypeError):
                pass  # 잘못된 메시지는 무시
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
        logger.debug("WebSocket 연결 예외 발생", exc_info=True)
