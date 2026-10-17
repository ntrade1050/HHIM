"""All tests use fakes: no Anthropic, Twilio, Microsoft or IONOS calls, no cost."""
import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.brain import Brain, to_messages
from app.config import get_settings
from app.email_channels import GraphMail, Incoming, strip_quoted
from app.guards import email_should_skip
from app.main import create_app, poll_email_once

TOKEN = "test-auth-token"
BASE = "https://desk.example.com"


class FakeAnthropic:
    def __init__(self, reply="Hello! We can help.", needs_human=False, fail=False):
        self.calls = []
        self.reply, self.needs_human, self.fail = reply, needs_human, fail
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("api down")
        block = SimpleNamespace(type="tool_use", input={
            "reply": self.reply, "needs_human": self.needs_human, "summary": "Test enquiry"})
        return SimpleNamespace(content=[block])


class FakeTwilio:
    def __init__(self):
        self.sent = []
        self.messages = self

    def create(self, **kw):
        self.sent.append(kw)


class FakeMail:
    def __init__(self, items):
        self.items, self.replies, self.done, self.sent = items, [], [], []

    async def fetch_new(self):
        return list(self.items)

    async def reply(self, msg, text):
        self.replies.append((msg.sender, text))

    async def mark_done(self, msg):
        self.done.append(msg.key)

    async def send(self, to, subject, text):
        self.sent.append((to, subject, text))


def settings(tmp_path, **over):
    s = get_settings()
    s.db_path = str(tmp_path / "t.db")
    s.knowledge_dir = str(tmp_path)
    (tmp_path / "biz.md").write_text("We offer free consultations. Phone 0333 000 0000.")
    s.business_name, s.public_base_url, s.twilio_auth_token = "H.HIM", BASE, TOKEN
    s.dry_run, s.auto_reply, s.poll_seconds = False, True, 0
    s.mailbox, s.handoff_email = "info@hhim.co.uk", "owner@hhim.co.uk"
    for k, v in over.items():
        setattr(s, k, v)
    return s


def signed_post(client, form):
    sig = RequestValidator(TOKEN).compute_signature(f"{BASE}/whatsapp", form)
    return client.post("/whatsapp", data=form, headers={"X-Twilio-Signature": sig})


def make(tmp_path, ai=None, mail=None, **over):
    s = settings(tmp_path, **over)
    ai, tw = ai or FakeAnthropic(), FakeTwilio()
    app = create_app(s, anthropic_client=ai, twilio_client=tw, mail=mail or FakeMail([]),
                     validator=RequestValidator(TOKEN))
    return app, ai, tw


# ---------------------------------------------------------------- WhatsApp
def test_whatsapp_reply_sent(tmp_path):
    app, ai, tw = make(tmp_path)
    with TestClient(app) as c:
        r = signed_post(c, {"MessageSid": "SM1", "From": "whatsapp:+447700900123", "Body": "Do you do VAT?"})
    assert r.status_code == 200 and "<Response>" in r.text
    assert tw.sent == [{"from_": "whatsapp:+14155238886", "to": "whatsapp:+447700900123", "body": "Hello! We can help."}]
    system = ai.calls[0]["system"]
    assert "free consultations" in system and "WhatsApp" in system


def test_whatsapp_bad_signature_rejected(tmp_path):
    app, ai, tw = make(tmp_path)
    with TestClient(app) as c:
        r = c.post("/whatsapp", data={"MessageSid": "SM1", "From": "x", "Body": "hi"},
                   headers={"X-Twilio-Signature": "forged"})
    assert r.status_code == 403 and not ai.calls and not tw.sent


def test_whatsapp_retry_not_answered_twice(tmp_path):
    app, ai, tw = make(tmp_path)
    form = {"MessageSid": "SM2", "From": "whatsapp:+447700900123", "Body": "hi"}
    with TestClient(app) as c:
        signed_post(c, form)
        signed_post(c, form)
    assert len(tw.sent) == 1


def test_whatsapp_remembers_conversation(tmp_path):
    app, ai, tw = make(tmp_path)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "A", "From": "whatsapp:+1", "Body": "I run a takeaway"})
        signed_post(c, {"MessageSid": "B", "From": "whatsapp:+1", "Body": "How much?"})
    msgs = ai.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "takeaway" in msgs[0]["content"]


def test_dry_run_sends_nothing(tmp_path):
    app, ai, tw = make(tmp_path, dry_run=True)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S", "From": "whatsapp:+1", "Body": "hi"})
    assert ai.calls and not tw.sent


def test_ai_failure_sends_holding_reply_and_alerts_staff(tmp_path):
    mail = FakeMail([])
    app, ai, tw = make(tmp_path, ai=FakeAnthropic(fail=True), mail=mail)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S", "From": "whatsapp:+1", "Body": "hi"})
    assert "book a free consultation" in tw.sent[0]["body"]
    assert "call" not in tw.sent[0]["body"].lower() and "get back to you" not in tw.sent[0]["body"]
    assert mail.sent and mail.sent[0][0] == "owner@hhim.co.uk"


def test_daily_limit_stops_loops(tmp_path):
    app, ai, tw = make(tmp_path, max_replies_per_contact_per_day=2)
    with TestClient(app) as c:
        for i in range(4):
            signed_post(c, {"MessageSid": f"S{i}", "From": "whatsapp:+1", "Body": "hi"})
    assert len(tw.sent) == 2


def test_long_reply_split_for_whatsapp(tmp_path):
    app, ai, tw = make(tmp_path, ai=FakeAnthropic(reply="x" * 3200))
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S", "From": "whatsapp:+1", "Body": "hi"})
    assert [len(m["body"]) for m in tw.sent] == [1500, 1500, 200]


# ---------------------------------------------------------------- Email
def incoming(key, sender="client@example.com", headers=None, text="Can you do my accounts?"):
    return Incoming(key=key, sender=sender, sender_name="Client", subject="Accounts", text=text,
                    headers=headers or {}, ref=key)


def run_poll(tmp_path, items, ai=None, **over):
    s = settings(tmp_path, **over)
    mail = FakeMail(items)
    app = create_app(s, anthropic_client=ai or FakeAnthropic(), twilio_client=FakeTwilio(), mail=mail,
                     validator=RequestValidator(TOKEN))
    n = asyncio.run(poll_email_once(app.state.service, mail, s))
    return n, mail


def test_email_reply_and_mark_read(tmp_path):
    n, mail = run_poll(tmp_path, [incoming("m1")])
    assert n == 1 and mail.replies == [("client@example.com", "Hello! We can help.")]
    assert mail.done == ["m1"]


def test_email_skips_robots_newsletters_and_self(tmp_path):
    items = [
        incoming("a", sender="no-reply@bank.com"),
        incoming("b", headers={"List-Unsubscribe": "<mailto:x>"}),
        incoming("c", headers={"Auto-Submitted": "auto-replied"}),
        incoming("d", sender="info@hhim.co.uk"),
    ]
    n, mail = run_poll(tmp_path, items)
    assert n == 0 and not mail.replies and sorted(mail.done) == ["a", "b", "c", "d"]


def test_email_same_message_only_once(tmp_path):
    s = settings(tmp_path)
    mail = FakeMail([incoming("m1")])
    app = create_app(s, anthropic_client=FakeAnthropic(), twilio_client=FakeTwilio(), mail=mail,
                     validator=RequestValidator(TOKEN))
    asyncio.run(poll_email_once(app.state.service, mail, s))
    asyncio.run(poll_email_once(app.state.service, mail, s))
    assert len(mail.replies) == 1


def test_email_needs_human_forwards_to_staff(tmp_path):
    n, mail = run_poll(tmp_path, [incoming("m1", text="I got an HMRC penalty letter")],
                       ai=FakeAnthropic(needs_human=True))
    assert mail.replies and mail.sent[0][0] == "owner@hhim.co.uk"
    assert "HMRC penalty" in mail.sent[0][2]


# ---------------------------------------------------------------- Units
def test_guard_allows_normal_customer():
    assert email_should_skip("jane@gmail.com", "info@hhim.co.uk", {"Precedence": ""}) is None


def test_strip_quoted_keeps_only_new_text():
    t = "Yes please book me in.\n\nOn Mon, 1 Jan 2026, H.HIM wrote:\n> old text"
    assert strip_quoted(t) == "Yes please book me in."


def test_to_messages_merges_and_starts_with_user():
    h = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    assert to_messages(h) == [{"role": "user", "content": "a\n\nb"}]


def test_graph_requests_match_microsoft_docs():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.content))
        if req.method == "GET":
            return httpx.Response(200, json={"value": [{
                "id": "AAM1", "subject": "Hi", "receivedDateTime": "2026-10-17T10:00:00Z",
                "from": {"emailAddress": {"address": "jane@gmail.com", "name": "Jane"}},
                "uniqueBody": {"content": "Do you do payroll?"}, "internetMessageHeaders": []}]})
        return httpx.Response(202)

    g = GraphMail("t", "", "", "info@hhim.co.uk", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def go():
        [m] = await g.fetch_new()
        assert m.sender == "jane@gmail.com" and m.text == "Do you do payroll?"
        await g.reply(m, "Yes\nwe do")
        await g.mark_done(m)

    asyncio.run(go())
    assert seen[1][:2] == ("POST", "/v1.0/users/info@hhim.co.uk/messages/AAM1/reply")
    assert json.loads(seen[1][2]) == {"comment": "Yes<br>we do"}
    assert seen[2][:2] == ("PATCH", "/v1.0/users/info@hhim.co.uk/messages/AAM1")
