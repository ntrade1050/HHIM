"""Booking tests: fixed clock, fake mail, no real emails."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.booking import BookingRules, all_slots, ics
from app.main import create_app
from tests.test_reply_desk import FakeAnthropic, FakeMail, FakeTwilio, settings

# Saturday 17 Oct 2026, 15:00 UK time (14:00 UTC, BST)
NOW = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)


def app_with(tmp_path, **over):
    s = settings(tmp_path, owner_email="imran@hhim.co.uk", **over)
    mail = FakeMail([])
    app = create_app(s, anthropic_client=FakeAnthropic(), twilio_client=FakeTwilio(), mail=mail,
                     validator=RequestValidator("x"), now=lambda: NOW)
    return app, mail


def details(start, email="jane@example.com"):
    return {"start": start, "name": "Jane Smith", "email": email, "phone": "07700 900123", "note": "Self-assessment"}


def test_slots_weekdays_only_and_respect_notice():
    slots = all_slots(BookingRules(), NOW)
    assert all(s.weekday() < 5 for s in slots)
    assert min(slots) > NOW  # nothing in the past or inside the 2-hour notice
    assert slots[0].strftime("%a %H:%M") == "Mon 09:30"  # weekend skipped, first slot Monday morning


def test_graph_sends_invite_as_file_attachment():
    import asyncio, base64, json
    import httpx
    from app.email_channels import GraphMail

    seen = []
    t = httpx.MockTransport(lambda req: seen.append(json.loads(req.content)) or httpx.Response(202))
    g = GraphMail("t", "", "", "info@hhim.co.uk", http=httpx.AsyncClient(transport=t))
    asyncio.run(g.send("a@b.com", "Hi", "Body", attachments=[("invite.ics", "text/calendar", b"BEGIN:VCALENDAR")]))
    att = seen[0]["message"]["attachments"][0]
    assert att["@odata.type"] == "#microsoft.graph.fileAttachment" and att["name"] == "invite.ics"
    assert base64.b64decode(att["contentBytes"]) == b"BEGIN:VCALENDAR"


def test_book_emails_client_and_owner_with_invite(tmp_path):
    app, mail = app_with(tmp_path)
    with TestClient(app) as c:
        first = c.get("/api/slots").json()["slots"][0]
        r = c.post("/api/book", json=details(first["start"]))
    assert r.status_code == 200 and "9:30" in r.json()["when"]
    recipients = [m[0] for m in mail.sent]
    assert recipients == ["jane@example.com", "imran@hhim.co.uk"]
    assert "confirmed" in mail.sent[0][2] and "07700 900123" in mail.sent[1][2]
    name, ctype, data = mail.attachments[0]
    assert (name, ctype) == ("invite.ics", "text/calendar")
    text = data.decode()
    assert "BEGIN:VEVENT" in text and "DTSTART:20261019T083000Z" in text  # 09:30 BST = 08:30 UTC
    assert "mailto:jane@example.com" in text and "mailto:imran@hhim.co.uk" in text


def test_slot_cannot_be_double_booked(tmp_path):
    app, mail = app_with(tmp_path)
    with TestClient(app) as c:
        start = c.get("/api/slots").json()["slots"][0]["start"]
        assert c.post("/api/book", json=details(start)).status_code == 200
        r = c.post("/api/book", json=details(start, "other@example.com"))
        assert r.status_code == 409 and "taken" in r.json()["error"]
        assert start not in [s["start"] for s in c.get("/api/slots").json()["slots"]]
    assert len(mail.sent) == 2


def test_bad_details_and_made_up_times_rejected(tmp_path):
    app, mail = app_with(tmp_path)
    with TestClient(app) as c:
        start = c.get("/api/slots").json()["slots"][0]["start"]
        assert c.post("/api/book", json=details(start, "not-an-email")).status_code == 409
        assert c.post("/api/book", json=details("2026-10-18T03:00:00Z")).status_code == 409  # Sunday 4am
        assert c.post("/api/book", json=details("2026-10-17T13:00:00Z")).status_code == 409  # in the past
        assert c.post("/api/book", content=b"[]", headers={"Content-Type": "application/json"}).status_code == 400
    assert not mail.sent


def test_dry_run_books_but_sends_no_email(tmp_path):
    app, mail = app_with(tmp_path, dry_run=True)
    with TestClient(app) as c:
        start = c.get("/api/slots").json()["slots"][0]["start"]
        assert c.post("/api/book", json=details(start)).status_code == 200
    assert not mail.sent


def test_booking_page_served(tmp_path):
    app, _ = app_with(tmp_path)
    with TestClient(app) as c:
        r = c.get("/book")
    assert r.status_code == 200 and "Book a free consultation" in r.text and "H.HIM" in r.text


def test_ics_escapes_text():
    data = ics("u1", NOW, 30, "Call; with, commas", "Line1\nLine2", "info@x.com", ["a@b.com"]).decode()
    assert "SUMMARY:Call\\; with\\, commas" in data and "DESCRIPTION:Line1\\nLine2" in data
    assert data.endswith("END:VCALENDAR\r\n")
