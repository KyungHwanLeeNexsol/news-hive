"""이메일 발송 서비스 - Gmail SMTP."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)

# Gmail SMTP 설정
_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def _build_verification_html(verify_link: str) -> str:
    """인증 링크 버튼 이메일 HTML 템플릿 생성."""
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NewsHive 이메일 인증</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f5f5;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background-color:#f5f5f5;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="520" cellpadding="0" cellspacing="0"
               style="background-color:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 2px 8px rgba(0,0,0,0.08);">

          <!-- 헤더 -->
          <tr>
            <td style="background-color:#1a1a2e;padding:32px 40px;text-align:center;">
              <span style="color:#e94560;font-size:24px;font-weight:700;
                           letter-spacing:-0.5px;">
                NewsHive
              </span>
              <p style="color:#a0aec0;font-size:13px;margin:8px 0 0;">
                AI 기반 뉴스 분석 플랫폼
              </p>
            </td>
          </tr>

          <!-- 본문 -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="margin:0 0 8px;font-size:22px;color:#1a1a2e;font-weight:600;">
                이메일 인증
              </h2>
              <p style="margin:0 0 28px;color:#718096;font-size:15px;line-height:1.6;">
                아래 버튼을 클릭하면 이메일 인증이 완료됩니다.
              </p>

              <!-- 인증 버튼 -->
              <div style="text-align:center;margin-bottom:28px;">
                <a href="{verify_link}"
                   style="display:inline-block;background-color:#1261c4;color:#ffffff;
                          font-size:16px;font-weight:600;text-decoration:none;
                          padding:14px 40px;border-radius:8px;letter-spacing:0.3px;">
                  이메일 인증하기
                </a>
              </div>

              <!-- 만료 안내 -->
              <div style="background-color:#fff5f5;border-left:4px solid #e94560;
                          border-radius:4px;padding:14px 16px;margin-bottom:24px;">
                <p style="margin:0;color:#c53030;font-size:14px;font-weight:500;">
                  &#9201; 이 링크는 <strong>24시간 후 만료</strong>됩니다
                </p>
              </div>

              <!-- 링크 직접 복사 안내 -->
              <p style="margin:0 0 8px;color:#a0aec0;font-size:12px;line-height:1.6;">
                버튼이 작동하지 않는 경우 아래 링크를 브라우저에 직접 붙여넣으세요:
              </p>
              <p style="margin:0 0 16px;word-break:break-all;">
                <a href="{verify_link}"
                   style="color:#1261c4;font-size:12px;text-decoration:none;">
                  {verify_link}
                </a>
              </p>

              <p style="margin:0;color:#a0aec0;font-size:13px;line-height:1.6;">
                본인이 요청하지 않으셨다면 이 이메일을 무시하셔도 됩니다.
                계정은 인증이 완료될 때까지 활성화되지 않습니다.
              </p>
            </td>
          </tr>

          <!-- 푸터 -->
          <tr>
            <td style="background-color:#f7fafc;padding:20px 40px;text-align:center;
                       border-top:1px solid #e2e8f0;">
              <p style="margin:0;color:#a0aec0;font-size:12px;">
                &copy; 2025 NewsHive. All rights reserved.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


async def send_verification_email(to_email: str, verify_link: str) -> None:
    """회원가입 이메일 인증 링크 발송.

    Args:
        to_email: 수신자 이메일 주소
        verify_link: 인증 URL (버튼 클릭 시 이동할 링크)

    Raises:
        aiosmtplib.SMTPException: SMTP 연결 또는 발송 실패 시 (SMTP 설정된 경우만)
    """
    # SMTP 미설정 시 개발 모드 폴백 - 로그에만 출력
    if not settings.SMTP_USER:
        logger.info(
            "[Dev] 이메일 인증 링크 발송 생략 (SMTP 미설정) | to=%s | link=%s",
            to_email,
            verify_link,
        )
        return

    subject = "[NewsHive] 이메일 인증을 완료해 주세요"
    html_body = _build_verification_html(verify_link)

    # MIME 멀티파트 메시지 구성
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.SMTP_USER
    message["To"] = to_email
    message.attach(MIMEText(html_body, "html", "utf-8"))

    # aiosmtplib STARTTLS 방식으로 비동기 발송
    await aiosmtplib.send(
        message,
        hostname=_SMTP_HOST,
        port=_SMTP_PORT,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        start_tls=True,
    )
    logger.info("인증 이메일 발송 완료 | to=%s", to_email)
