from __future__ import annotations

import logging
import os
from typing import Final

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID: Final[str | None] = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN: Final[str | None] = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM: Final[str | None] = os.getenv("TWILIO_FROM")
TWILIO_MESSAGING_SERVICE_SID: Final[str | None] = os.getenv("TWILIO_MESSAGING_SERVICE_SID")

GATEWAY_URL: Final[str | None] = os.getenv("SMS_GATEWAY_URL")
GATEWAY_KEY: Final[str | None] = os.getenv("SMS_GATEWAY_KEY")
GATEWAY_SENDER: Final[str | None] = os.getenv("SMS_SENDER_ID")


def send_sms_twilio(to: str, body: str) -> None:
    """Send an SMS through Twilio's REST API."""
    if not to:
        raise ValueError("SMS recipient number is required")
    if not body:
        raise ValueError("SMS body is required")

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        raise RuntimeError("Twilio credentials are not configured")
    if not (TWILIO_FROM or TWILIO_MESSAGING_SERVICE_SID):
        raise RuntimeError("Twilio sender is not configured")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    payload = {"To": to, "Body": body}
    if TWILIO_MESSAGING_SERVICE_SID:
        payload["MessagingServiceSid"] = TWILIO_MESSAGING_SERVICE_SID
    else:
        payload["From"] = TWILIO_FROM

    try:
        response = requests.post(
            url,
            data=payload,
            auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=20,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.error("Twilio request failed for %s: %s", to, exc)
        raise RuntimeError(f"Twilio request failed: {exc}") from exc

    if response.status_code >= 300:
        logger.error("Twilio returned %s for %s: %s", response.status_code, to, response.text)
        raise RuntimeError(f"Twilio returned {response.status_code}: {response.text}")


def send_sms_gateway(to: str, body: str) -> None:
    """Optional helper for a custom SMS gateway."""
    if not to:
        raise ValueError("SMS recipient number is required")
    if not body:
        raise ValueError("SMS body is required")

    if not (GATEWAY_URL and GATEWAY_KEY and GATEWAY_SENDER):
        raise RuntimeError("SMS gateway is not configured")

    try:
        response = requests.post(
            GATEWAY_URL,
            json={
                "to": to,
                "message": body,
                "sender": GATEWAY_SENDER,
                "api_key": GATEWAY_KEY,
            },
            timeout=20,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.error("SMS gateway request failed for %s: %s", to, exc)
        raise RuntimeError(f"SMS gateway request failed: {exc}") from exc

    if response.status_code >= 300:
        logger.error("SMS gateway returned %s for %s: %s", response.status_code, to, response.text)
        raise RuntimeError(f"SMS gateway returned {response.status_code}: {response.text}")
