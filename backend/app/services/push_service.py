"""Web Push 알림 서비스 - VAPID + pywebpush."""

import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def send_push_notification(
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
    title: str,
    body: str,
    url: str = "/",
) -> bool:
    """Web Push 알림 발송.

    Args:
        endpoint: 브라우저 푸시 구독 엔드포인트 URL
        p256dh_key: 클라이언트 공개 키 (base64url 인코딩)
        auth_key: 인증 시크릿 (base64url 인코딩)
        title: 알림 제목
        body: 알림 본문
        url: 알림 클릭 시 이동할 URL

    Returns:
        True: 발송 성공, False: 발송 실패 또는 VAPID 미설정
    """
    # VAPID 미설정 시 개발 모드 폴백
    if not settings.VAPID_PRIVATE_KEY:
        logger.info(
            "[Dev] Web Push 발송 생략 (VAPID 미설정) | title=%s | url=%s",
            title,
            url,
        )
        return False

    try:
        # 지연 임포트: pywebpush가 선택적 의존성이므로 런타임에 로드
        from pywebpush import WebPusher  # type: ignore[import-untyped]

        # 알림 페이로드 구성
        payload = json.dumps({"title": title, "body": body, "url": url})

        # 구독 정보 딕셔너리
        subscription_info = {
            "endpoint": endpoint,
            "keys": {
                "p256dh": p256dh_key,
                "auth": auth_key,
            },
        }

        # VAPID 클레임 설정
        vapid_claims = {
            "sub": f"mailto:{settings.SMTP_USER or 'admin@newshive.app'}",
        }

        # WebPusher 인스턴스 생성 및 발송
        pusher = WebPusher(subscription_info)
        response = pusher.send(
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims=vapid_claims,
        )

        # 201 Created 또는 200 OK 를 성공으로 처리
        if response.status_code in (200, 201):
            logger.info("Web Push 발송 완료 | title=%s | status=%d", title, response.status_code)
            return True

        # 410 Gone: 구독이 만료됨 - DB에서 제거 필요 (호출자가 처리)
        if response.status_code == 410:
            logger.warning("Web Push 구독 만료 (410) | endpoint 삭제 필요 | endpoint=%s", endpoint)
            return False

        logger.warning(
            "Web Push 발송 실패 | status=%d | endpoint=%s",
            response.status_code,
            endpoint,
        )
        return False

    except ImportError:
        logger.error("pywebpush 패키지가 설치되지 않았습니다. pip install pywebpush 실행 필요")
        return False
    except Exception:  # noqa: BLE001
        logger.exception("Web Push 발송 중 예외 발생 | endpoint=%s", endpoint)
        return False


def generate_vapid_keys() -> dict[str, str]:
    """VAPID 키 쌍 생성. 최초 설정 시 1회 실행.

    Returns:
        {"private_key": str, "public_key": str}
        private_key: .env 의 VAPID_PRIVATE_KEY 에 설정
        public_key: 프론트엔드 applicationServerKey 에 사용

    Raises:
        ImportError: py_vapid 패키지 미설치 시
    """
    from cryptography.hazmat.primitives.serialization import (  # type: ignore[import-untyped]
        Encoding,
        PublicFormat,
    )
    from py_vapid import Vapid  # type: ignore[import-untyped]

    vapid = Vapid()
    vapid.generate_keys()

    private_key: str = vapid.private_pem().decode("utf-8")
    public_key: str = vapid.public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    logger.info("VAPID 키 쌍 생성 완료. .env 에 VAPID_PRIVATE_KEY 를 설정하세요.")
    return {"private_key": private_key, "public_key": public_key}
