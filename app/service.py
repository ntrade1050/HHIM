"""One flow for every channel: remember → answer → send → hand over if needed."""
import logging
from typing import Awaitable, Callable

from .brain import Brain
from .guards import mask
from .store import Store

log = logging.getLogger("reply_desk")

Sender = Callable[[str], Awaitable[None]]
Notifier = Callable[[str, str], Awaitable[None]]  # (subject, text)


class ReplyService:
    def __init__(self, store: Store, brain: Brain, settings, notify: Notifier | None = None, bookings=None):
        self.store, self.brain, self.s = store, brain, settings
        self.notify, self.bookings = notify, bookings

    async def _try_booking(self, channel: str, contact: str, answer) -> str | None:
        """If the AI asked to book, book it for real and return the confirmation (or a retry message)."""
        b = answer.book or {}
        if not (self.bookings and b.get("slot") and b.get("name") and b.get("email")):
            return None
        phone = str(b.get("phone") or "")
        if channel == "whatsapp" and len("".join(c for c in phone if c.isdigit())) < 10:
            phone = contact.replace("whatsapp:", "")
        from .booking import BookingError  # local import keeps modules independent

        try:
            result = await self.bookings.book(str(b["slot"]), str(b["name"]), str(b["email"]), phone,
                                              f"Booked in {channel} chat. {answer.summary}")
        except BookingError as exc:
            free = self.bookings.free_slots()[:3]
            options = " ".join(f"{i}) {s['day']} {s['time']}" for i, s in enumerate(free, 1))
            return f"{exc} Free times: {options}" if options else str(exc)
        first = str(b["name"]).split()[0]
        text = (f"Confirmed, {first}: your free consultation is booked for {result['when']} (UK time). "
                f"A confirmation with a calendar invite is on its way to {result['email']}.")
        if channel == "email":
            text += f"\n\nKind regards,\n{self.s.business_name}"
        return text

    async def handle(self, channel: str, contact: str, text: str, send: Sender, label: str = "") -> str:
        """Returns what happened: 'sent', 'dry_run', 'paused', 'limit'."""
        self.store.add_turn(channel, contact, "user", text)

        if not self.s.auto_reply:
            await self._handover(channel, contact, text, None, "Auto-reply is paused")
            return "paused"
        if self.store.sends_last_day(channel, contact) >= self.s.max_replies_per_contact_per_day:
            log.warning("limit reached channel=%s contact=%s", channel, mask(contact))
            return "limit"

        slots = self.bookings.free_slots()[:12] if self.bookings else []
        answer = await self.brain.answer(channel, self.store.history(channel, contact), slots)
        booked_text = await self._try_booking(channel, contact, answer)
        if booked_text:
            answer.reply = booked_text

        if self.s.dry_run:
            log.info("DRY RUN channel=%s contact=%s needs_human=%s", channel, mask(contact), answer.needs_human)
            outcome = "dry_run"
        else:
            await send(answer.reply)
            outcome = "sent"
        self.store.add_turn(channel, contact, "assistant", answer.reply)
        self.store.record_send(channel, contact)
        log.info("replied channel=%s contact=%s needs_human=%s", channel, mask(contact), answer.needs_human)

        if answer.needs_human:
            await self._handover(channel, contact, text, answer.reply, answer.summary, label)
        return outcome

    async def _handover(self, channel, contact, text, reply, summary, label=""):
        if not (self.notify and self.s.handoff_email):
            return
        body = (
            f"A customer needs a person.\n\nChannel: {channel}\nFrom: {label or contact}\n"
            f"Summary: {summary}\n\nTheir message:\n{text}\n\n"
            f"Automatic reply sent:\n{reply or '(none)'}\n"
        )
        try:
            await self.notify(f"[Enquiry] {summary}"[:150], body)
        except Exception:
            log.exception("handover email failed")
