
# api_guard/sms.py
import os
import requests

# يجب أن تكون هذه "أسماء" متغيرات البيئة، وليس القيم
TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID", "AC4c745068124b3f49da80d7b87fc271c6")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "ec88f3f09f1912c57232a88c8401b98d")
TWILIO_FROM  = os.getenv("TWILIO_FROM", "+19713091287")                # مثال: +19713091287
TWILIO_MSID  = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")  # بديل اختياري

def send_sms_twilio(to: str, body: str) -> None:
    """إرسال عبر Twilio مع رسائل خطأ واضحة."""
    if not (TWILIO_SID and TWILIO_TOKEN and (TWILIO_FROM or TWILIO_MSID)):
        raise RuntimeError(
            "Twilio env vars missing "
            "(TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM or TWILIO_MESSAGING_SERVICE_SID)"
        )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    data = {"To": to, "Body": body}
    if TWILIO_MSID:
        data["MessagingServiceSid"] = TWILIO_MSID
    else:
        data["From"] = TWILIO_FROM

    resp = requests.post(url, data=data, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"Twilio {resp.status_code}: {resp.text}")


# (اختياري) بوابة محلية
GATEWAY_URL   = os.getenv("SMS_GATEWAY_URL", "")
GATEWAY_KEY   = os.getenv("SMS_GATEWAY_KEY", "")
GATEWAY_SENDER= os.getenv("SMS_SENDER_ID", "")

def send_sms_gateway(to: str, body: str) -> None:
    if not (GATEWAY_URL and GATEWAY_KEY and GATEWAY_SENDER):
        raise RuntimeError("SMS gateway env vars missing (SMS_GATEWAY_URL / SMS_GATEWAY_KEY / SMS_SENDER_ID)")
    r = requests.post(GATEWAY_URL,
                      json={"to": to, "message": body, "sender": GATEWAY_SENDER, "api_key": GATEWAY_KEY},
                      timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"Gateway {r.status_code}: {r.text}")
