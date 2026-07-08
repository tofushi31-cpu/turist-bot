import logging
import os
import uuid

from yookassa import Configuration, Payment

logger = logging.getLogger("turist-bot")

YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")


def is_configured() -> bool:
    return bool(YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)


def create_payment_link(booking_id, amount, description):
    if not is_configured():
        logger.info("YooKassa не настроена — ссылка на оплату не создана для заявки #%s", booking_id)
        return None

    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY

    try:
        payment = Payment.create(
            {
                "amount": {"value": f"{float(amount):.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://t.me/"},
                "capture": True,
                "description": description,
                "metadata": {"booking_id": booking_id},
            },
            str(uuid.uuid4()),
        )
        return payment.confirmation.confirmation_url
    except Exception:
        logger.exception("Не удалось создать ссылку на оплату YooKassa для заявки #%s", booking_id)
        return None
