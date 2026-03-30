"""글로벌 이벤트 버스 -- 서비스에서 이벤트 발생 시 WebSocket으로 브로드캐스트.

서비스 코드는 WebSocket 구현을 직접 참조하지 않고,
이 모듈의 broadcast_event()만 호출하면 된다.
ConnectionManager가 등록되어 있지 않으면 조용히 무시한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.websocket import ConnectionManager

logger = logging.getLogger(__name__)

# 모듈 레벨 싱글톤 참조
_event_bus: Optional["ConnectionManager"] = None


def set_event_bus(manager: "ConnectionManager") -> None:
    """앱 시작 시 ConnectionManager를 등록한다."""
    global _event_bus
    _event_bus = manager
    logger.info("이벤트 버스 등록 완료")


def get_event_bus() -> Optional["ConnectionManager"]:
    """현재 등록된 ConnectionManager를 반환한다."""
    return _event_bus


def clear_event_bus() -> None:
    """앱 종료 시 이벤트 버스 참조를 해제한다."""
    global _event_bus
    _event_bus = None


async def broadcast_event(topic: str, data: dict) -> None:
    """서비스에서 호출 -- WebSocket으로 이벤트를 전파한다.

    ConnectionManager가 등록되어 있지 않으면 조용히 무시한다.
    동기 컨텍스트(스케줄러 등)에서 호출해도 안전하다.
    """
    bus = _event_bus
    if bus is None:
        return

    try:
        await bus.broadcast(topic, data)
    except Exception:
        logger.warning("이벤트 브로드캐스트 실패: topic=%s", topic, exc_info=True)


def fire_event(topic: str, data: dict) -> None:
    """동기 컨텍스트에서 이벤트를 발생시키는 헬퍼.

    스케줄러(APScheduler) 콜백처럼 이벤트 루프가 없는 곳에서 사용한다.
    내부적으로 asyncio.create_task 또는 새 이벤트 루프를 사용한다.
    """
    bus = _event_bus
    if bus is None:
        return

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_event(topic, data))
    except RuntimeError:
        # 이벤트 루프가 없는 동기 컨텍스트
        try:
            asyncio.run(broadcast_event(topic, data))
        except Exception:
            logger.warning("동기 컨텍스트 이벤트 발생 실패: topic=%s", topic, exc_info=True)
