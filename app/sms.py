"""SMS via Twilio, and UK phone-number tidying."""
import asyncio
import logging
import re

from .guards import mask

log = logging.getLogger("reply_desk")


def to_e164(phone: str, default_country: str = "44") -> str:
    """'07700 900123' -> '+447700900123'; 'whatsapp:+44...' -> '+44...'. Returns '' if it can't be a phone number."""
    p = (phone or "").replace("whatsapp:", "").split("#")[0].strip()
    plus = p.startswith("+")
    digits = re.sub(r"\D", "", p)
    if plus:
        out = "+" + digits
    elif digits.startswith("00"):
        out = "+" + digits[2:]
    elif digits.startswith("0"):
        out = "+" + default_country + digits[1:]
    elif digits.startswith(default_country):
        out = "+" + digits
    else:
        return ""
    return out if 11 <= len(out) <= 16 else ""


class Sms:
    def __init__(self, twilio_client, sender: str, dry_run: bool = False):
        self.client, self.sender, self.dry_run = twilio_client, sender, dry_run

    @property
    def ready(self) -> bool:
        return bool(self.client and self.sender)

    async def send(self, to: str, text: str) -> bool:
        number = to_e164(to)
        if not (self.ready and number):
            log.info("sms skipped (not configured or bad number) to=%s", mask(to))
            return False
        if self.dry_run:
            log.info("DRY RUN sms to=%s", mask(number))
            return True
        try:
            await asyncio.to_thread(self.client.messages.create, from_=self.sender, to=number, body=text[:640])
            return True
        except Exception:
            log.exception("sms failed to=%s", mask(number))
            return False
