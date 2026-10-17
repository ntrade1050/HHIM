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
    def __init__(self, store: Store, brain: Brain, settings, notify: Notifier | None = None):
        self.store, self.brain, self.s = store, brain, settings
        self.notify = notify

    async def handle(self, channel: str, contact: str, text: str, send: Sender, label: str = "") -> str:
        """Returns what happened: 'sent', 'dry_run', 'paused', 'limit'."""
        self.store.add_turn(channel, contact, "user", text)

        if not self.s.auto_reply:
            await self._handover(channel, contact, text, None, "Auto-reply is paused")
            return "paused"
        if self.store.sends_last_day(channel, contact) >= self.s.max_replies_per_contact_per_day:
            log.warning("limit reached channel=%s contact=%s", channel, mask(contact))
            return "limit"

        answer = await self.brain.answer(channel, self.store.history(channel, contact))

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
