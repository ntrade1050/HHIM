"""Appointment booking: free slots, safe booking (no double-booking), and confirmation emails with a calendar invite."""
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class BookingRules:
    tz: str = "Europe/London"
    days: str = "mon,tue,wed,thu,fri"
    start: str = "09:30"         # first appointment
    end: str = "17:00"           # appointments must finish by this time
    minutes: int = 30
    days_ahead: int = 10
    min_notice_hours: int = 2
    title: str = "Free consultation"

    @property
    def zone(self):
        return ZoneInfo(self.tz)


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def all_slots(rules: BookingRules, now: datetime) -> list[datetime]:
    """Every bookable start time (timezone-aware, local) from now to days_ahead."""
    zone, open_days = rules.zone, {d.strip().lower()[:3] for d in rules.days.split(",")}
    local_now = now.astimezone(zone)
    earliest = local_now + timedelta(hours=rules.min_notice_hours)
    out = []
    for i in range(rules.days_ahead + 1):
        d: date = local_now.date() + timedelta(days=i)
        if DAY_NAMES[d.weekday()] not in open_days:
            continue
        t = datetime.combine(d, _hm(rules.start), zone)
        last = datetime.combine(d, _hm(rules.end), zone) - timedelta(minutes=rules.minutes)
        while t <= last:
            if t >= earliest:
                out.append(t)
            t += timedelta(minutes=rules.minutes)
    return out


def to_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human(dt: datetime, rules: BookingRules) -> str:
    local = dt.astimezone(rules.zone)
    return local.strftime("%A %d %B %Y at %H:%M").replace(" 0", " ")


def ics(uid: str, start: datetime, minutes: int, title: str, description: str, organizer: str,
        attendees: list[str]) -> bytes:
    """A standard iCalendar (RFC 5545) event that Outlook, Gmail and Apple Calendar can add."""
    fmt = "%Y%m%dT%H%M%SZ"
    s = start.astimezone(timezone.utc)
    e = s + timedelta(minutes=minutes)

    def esc(v: str) -> str:
        return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Reply Desk//Bookings//EN", "METHOD:PUBLISH", "BEGIN:VEVENT",
        f"UID:{uid}", f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{s.strftime(fmt)}", f"DTEND:{e.strftime(fmt)}",
        f"SUMMARY:{esc(title)}", f"DESCRIPTION:{esc(description)}",
    ]
    if organizer:
        lines.append(f"ORGANIZER:mailto:{organizer}")
    lines += [f"ATTENDEE;ROLE=REQ-PARTICIPANT:mailto:{a}" for a in attendees if a]
    lines += ["STATUS:CONFIRMED", "END:VEVENT", "END:VCALENDAR"]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


class BookingError(Exception):
    pass


class BookingService:
    def __init__(self, store, mail, rules: BookingRules, business: str, owner_email: str, mailbox: str,
                 dry_run: bool = False, now=lambda: datetime.now(timezone.utc), sms=None, owner_phone: str = ""):
        self.store, self.mail, self.rules = store, mail, rules
        self.business, self.owner_email, self.mailbox = business, owner_email, mailbox
        self.dry_run, self.now = dry_run, now
        self.sms, self.owner_phone = sms, owner_phone

    @property
    def wants_email(self) -> bool:
        """Only ask clients for an email address when we can actually send one."""
        return bool(self.mail)

    def free_slots(self) -> list[dict]:
        taken = self.store.booked_keys()
        return [
            {"start": to_key(t), "day": t.strftime("%a %d %b").replace(" 0", " "), "time": t.strftime("%H:%M")}
            for t in all_slots(self.rules, self.now()) if to_key(t) not in taken
        ]

    async def book(self, start: str, name: str, email: str, phone: str, note: str = "", source: str = "web") -> dict:
        name, email, phone, note = name.strip()[:100], email.strip().lower()[:200], phone.strip()[:40], note.strip()[:1000]
        if not name:
            raise BookingError("Please enter your name.")
        if (email or self.wants_email) and not EMAIL_RE.match(email):
            raise BookingError("Please enter a valid email address so we can send your confirmation.")
        if len(re.sub(r"\D", "", phone)) < 10:
            raise BookingError("Please enter a valid phone number.")
        valid = {to_key(t): t for t in all_slots(self.rules, self.now())}
        if start not in valid:
            raise BookingError("That time isn't available. Please choose another slot.")
        booking_id = uuid.uuid4().hex[:12]
        if not self.store.add_booking(booking_id, start, name, email, phone, note, source):
            raise BookingError("Sorry, that slot has just been taken. Please choose another time.")

        when = human(valid[start], self.rules)
        result = {"id": booking_id, "start": start, "when": when, "name": name, "email": email, "emailed": [],
                  "texted": []}
        await self._text(when, name, email, phone, note, source, result)
        await self._confirm(booking_id, valid[start], when, name, email, phone, note, result)
        return result

    async def _text(self, when, name, email, phone, note, source, result):
        """SMS: the client (unless they booked inside WhatsApp, where the chat confirms) and the owner."""
        if not self.sms:
            return
        first = name.split()[0]
        if source != "whatsapp":
            ok = await self.sms.send(phone, f"{self.business}: Hi {first}, your free consultation is confirmed for "
                                            f"{when} (UK time). We'll text you a reminder the day before.")
            if ok:
                result["texted"].append("client")
        if self.owner_phone:
            ok = await self.sms.send(self.owner_phone, f"New booking: {name}, {when}. Phone {phone}"
                                     + (f", {email}" if email else "") + f". Via {source}." + (f" {note}" if note else ""))
            if ok:
                result["texted"].append("owner")

    async def send_due_reminders(self, hours_before: int = 24) -> int:
        """Text each client once, about `hours_before` ahead of their appointment."""
        if not (self.sms and self.sms.ready):
            return 0
        now = self.now()
        sent = 0
        for b in self.store.due_reminders(to_key(now), to_key(now + timedelta(hours=hours_before))):
            start = datetime.strptime(b["start_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            first = b["name"].split()[0]
            self.store.mark_reminded(b["id"])  # mark first so a crash can't cause repeat texts
            if await self.sms.send(b["phone"], f"{self.business}: Reminder, {first}: your free consultation is "
                                               f"{human(start, self.rules)} (UK time)."):
                sent += 1
        return sent

    async def _confirm(self, booking_id, start, when, name, email, phone, note, result):
        if not (self.mail and email):
            return
        invite = ics(f"{booking_id}@reply-desk", start, self.rules.minutes, f"{self.rules.title} - {self.business}",
                     f"{self.rules.title} with {self.business}.\nClient: {name}, {phone}, {email}",
                     self.mailbox, [email, self.owner_email])
        attachment = ("invite.ics", "text/calendar", invite)
        first = name.split()[0]
        client_text = (
            f"Hi {first},\n\nYour {self.rules.title.lower()} with {self.business} is confirmed for {when} "
            f"(UK time, {self.rules.minutes} minutes).\n\nThe calendar invite is attached so you can add it to your "
            f"calendar. If you need to change the time, just reply to this email.\n\nKind regards,\n{self.business}"
        )
        owner_text = (
            f"New booking: {self.rules.title}\n\nWhen: {when} ({self.rules.minutes} minutes)\nName: {name}\n"
            f"Email: {email}\nPhone: {phone}\n" + (f"\nNotes:\n{note}\n" if note else "") +
            "\nThe calendar invite is attached."
        )
        sends = [(email, f"Confirmed: {self.rules.title} on {when}", client_text, "client")]
        if self.owner_email:
            sends.append((self.owner_email, f"New booking: {name}, {when}", owner_text, "owner"))
        for to, subject, text, who in sends:
            if self.dry_run:
                result["emailed"].append(f"{who} (dry run)")
                continue
            try:
                await self.mail.send(to, subject, text, attachments=[attachment])
                result["emailed"].append(who)
            except Exception:
                result.setdefault("email_failed", []).append(who)
