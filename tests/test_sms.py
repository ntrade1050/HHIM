"""SMS confirmations, owner alerts and reminders, with email switched off (Outlook move). Fakes only."""
import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.main import create_app
from app.sms import to_e164
from tests.test_booking import NOW
from tests.test_reply_desk import TOKEN, FakeAnthropic, FakeTwilio, settings, signed_post

OWNER = "07700 900999"


def make(tmp_path, ai=None, clock=None, **over):
    s = settings(tmp_path, sms_from="HHIM", owner_phone=OWNER, email_provider="off", owner_email="",
                 handoff_email="", **over)
    tw = FakeTwilio()
    clock = clock or {"now": NOW}
    app = create_app(s, anthropic_client=ai or FakeAnthropic(), twilio_client=tw, mail=None,
                     validator=RequestValidator(TOKEN), now=lambda: clock["now"])
    return app, tw, clock


def sms(tw):
    return [m for m in tw.sent if m["from_"] == "HHIM"]


def whatsapp(tw):
    return [m for m in tw.sent if m["from_"].startswith("whatsapp:")]


def test_uk_numbers_normalised():
    assert to_e164("07700 900123") == "+447700900123"
    assert to_e164("whatsapp:+447700900123") == "+447700900123"
    assert to_e164("0044 7700 900123") == "+447700900123"
    assert to_e164("447700900123") == "+447700900123"
    assert to_e164("12345") == "" and to_e164("") == ""


def test_web_booking_texts_client_and_owner_without_email(tmp_path):
    app, tw, _ = make(tmp_path)
    with TestClient(app) as c:
        assert 'id="email"' not in c.get("/book").text  # no email field while email is off
        start = c.get("/api/slots").json()["slots"][0]["start"]
        r = c.post("/api/book", json={"start": start, "name": "Jane Smith", "email": "", "phone": "07700 900123"})
    assert r.status_code == 200
    to = [m["to"] for m in sms(tw)]
    assert to == ["+447700900123", "+447700900999"]
    assert "confirmed for Monday 19 October 2026 at 9:30" in sms(tw)[0]["body"]
    assert "Jane Smith" in sms(tw)[1]["body"] and "Via web" in sms(tw)[1]["body"]


def test_whatsapp_booking_confirms_in_chat_and_texts_owner_only(tmp_path):
    ai = FakeAnthropic(reply="(model)", book={"slot": "2026-10-19T08:30:00Z", "name": "Jane Smith"})
    app, tw, _ = make(tmp_path, ai=ai)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+447700900123", "Body": "Option 1, Jane Smith"})
    assert whatsapp(tw)[0]["body"].startswith("Confirmed, Jane") and "reminder the day before" in whatsapp(tw)[0]["body"]
    assert "calendar invite" not in whatsapp(tw)[0]["body"]  # no email promised while email is off
    assert [m["to"] for m in sms(tw)] == ["+447700900999"]  # owner only; client already has the chat


def test_ai_not_asked_for_email_while_email_off(tmp_path):
    ai = FakeAnthropic()
    app, tw, _ = make(tmp_path, ai=ai)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+447700900123", "Body": "Book me in"})
    system = ai.calls[0]["system"]
    assert "anything still missing: their full name." in system and "email address" not in system


def test_needs_human_texts_owner(tmp_path):
    app, tw, _ = make(tmp_path, ai=FakeAnthropic(reply="That needs an accountant.", needs_human=True))
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+447700900123", "Body": "HMRC penalty letter"})
    owner = [m for m in sms(tw) if m["to"] == "+447700900999"]
    assert owner and "HMRC penalty letter" in owner[0]["body"]


def test_reminder_sent_once_day_before(tmp_path):
    app, tw, clock = make(tmp_path)
    with TestClient(app) as c:
        start = c.get("/api/slots").json()["slots"][0]["start"]  # Mon 09:30 UK
        c.post("/api/book", json={"start": start, "name": "Jane Smith", "phone": "07700 900123"})
    bookings = app.state.bookings
    before = len(sms(tw))
    assert asyncio.run(bookings.send_due_reminders(24)) == 0  # Saturday: too early
    clock["now"] = NOW + timedelta(hours=19)  # Sunday 10:00 UK, 23.5h before Monday 09:30
    assert asyncio.run(bookings.send_due_reminders(24)) == 1
    assert asyncio.run(bookings.send_due_reminders(24)) == 0  # never twice
    reminder = sms(tw)[before]
    assert reminder["to"] == "+447700900123" and "Reminder, Jane" in reminder["body"]


def test_dry_run_sends_no_sms(tmp_path):
    app, tw, _ = make(tmp_path, dry_run=True)
    with TestClient(app) as c:
        start = c.get("/api/slots").json()["slots"][0]["start"]
        assert c.post("/api/book", json={"start": start, "name": "Jane", "phone": "07700 900123"}).status_code == 200
    assert not tw.sent
