import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger("turist-bot")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER


def is_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD)


def send_email(to_email: str, subject: str, body: str) -> bool:
    if not is_configured():
        logger.info("Почта не настроена — письмо на %s не отправлено", to_email)
        return False

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
        return True
    except Exception:
        logger.exception("Не удалось отправить письмо на %s", to_email)
        return False
