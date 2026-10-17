"""In-chat booking on WhatsApp, and swappable AI providers (DeepSeek etc.). All fakes, no cost."""
import asyncio
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.llm import OpenAICompatibleLLM, build_llm
from tests.test_booking import NOW
from tests.test_reply_desk import TOKEN, FakeAnthropic, FakeMail, FakeTwilio, settings, signed_post
from app.main import create_app


def first_slot_from_prompt(kw):
    """Pick the first [code] the model was shown, like a customer choosing option 1."""
    return re.search(r"\[(\d{4}-\d\d-\d\dT[\d:]+Z)\]", kw["system"]).group(1)


def make(tmp_path, ai):
    s = settings(tmp_path, owner_email="imran@hhim.co.uk")
    mail, tw = FakeMail([]), FakeTwilio()
    app = create_app(s, anthropic_client=ai, twilio_client=tw, mail=mail, validator=RequestValidator(TOKEN),
                     now=lambda: NOW)
    return app, mail, tw


def test_ai_is_shown_real_free_times(tmp_path):
    ai = FakeAnthropic()
    app, mail, tw = make(tmp_path, ai)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+447700900123", "Body": "Can I book?"})
    assert "Mon 19 Oct 09:30 [2026-10-19T08:30:00Z]" in ai.calls[0]["system"]


def test_whatsapp_books_in_chat_and_emails_both(tmp_path):
    ai = FakeAnthropic(reply="(model text)", book=lambda kw: {
        "slot": first_slot_from_prompt(kw), "name": "Jane Smith", "email": "jane@example.com"})
    app, mail, tw = make(tmp_path, ai)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+447700900123", "Body": "Option 1. Jane Smith, jane@example.com"})
        free = [s["start"] for s in c.get("/api/slots").json()["slots"]]
    body = tw.sent[0]["body"]
    assert body.startswith("Confirmed, Jane") and "Monday 19 October 2026 at 9:30" in body
    assert [m[0] for m in mail.sent] == ["jane@example.com", "imran@hhim.co.uk"]
    assert "447700900123" in mail.sent[1][2]  # WhatsApp number used as the phone
    assert "2026-10-19T08:30:00Z" not in free  # the slot is now taken


def test_taken_slot_offers_alternatives(tmp_path):
    ai = FakeAnthropic(book={"slot": "2026-10-19T08:30:00Z", "name": "Jane", "email": "jane@example.com"})
    app, mail, tw = make(tmp_path, ai)
    with TestClient(app) as c:
        c.post("/api/book", json={"start": "2026-10-19T08:30:00Z", "name": "Sam", "email": "sam@example.com",
                                  "phone": "07700900999"})
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+447700900123", "Body": "9:30 Monday please"})
    body = tw.sent[0]["body"]
    assert "just been taken" in body and "1) Mon 19 Oct 10:00" in body


def test_no_booking_without_email(tmp_path):
    ai = FakeAnthropic(reply="What's your email?", book={"slot": "2026-10-19T08:30:00Z", "name": "Jane", "email": ""})
    app, mail, tw = make(tmp_path, ai)
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+1", "Body": "Monday 9:30"})
    assert tw.sent[0]["body"] == "What's your email?" and not mail.sent


# ---------------------------------------------------------------- other AI providers
def test_deepseek_request_and_json_parsing():
    seen = []

    def handler(req):
        seen.append((str(req.url), req.headers["Authorization"], json.loads(req.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"reply": "Hi", "needs_human": False, "summary": "s"})}}]})

    llm = OpenAICompatibleLLM("https://api.deepseek.com", "sk-test", "deepseek-flash",
                              http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = asyncio.run(llm.complete_json("Be brief.", [{"role": "user", "content": "hi"}],
                                        {"type": "object", "properties": {"reply": {}}}))
    url, auth, body = seen[0]
    assert url == "https://api.deepseek.com/chat/completions" and auth == "Bearer sk-test"
    assert body["model"] == "deepseek-flash" and body["response_format"] == {"type": "json_object"}
    assert "json" in body["messages"][0]["content"]  # DeepSeek requires the word json in the prompt
    assert out["reply"] == "Hi"


def test_empty_model_reply_falls_back_to_holding_message(tmp_path):
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    llm = OpenAICompatibleLLM("https://x", "k", "m", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    s = settings(tmp_path)
    tw = FakeTwilio()
    app = create_app(s, llm=llm, twilio_client=tw, mail=FakeMail([]), validator=RequestValidator(TOKEN))
    with TestClient(app) as c:
        signed_post(c, {"MessageSid": "S1", "From": "whatsapp:+1", "Body": "hi"})
    assert "book a free consultation" in tw.sent[0]["body"]


def test_provider_presets(tmp_path):
    s = settings(tmp_path, llm_provider="deepseek", llm_api_key="k", llm_model="", llm_base_url="")
    llm = build_llm(s)
    assert (llm.base_url, llm.model) == ("https://api.deepseek.com", "deepseek-flash")
    s.llm_provider, s.llm_api_key = "deepseek", ""
    with pytest.raises(RuntimeError):
        build_llm(s)


def test_local_test_chat_only_when_enabled(tmp_path):
    app, mail, tw = make(tmp_path, FakeAnthropic(reply="Limited company or sole trader?"))
    with TestClient(app) as c:
        assert c.get("/chat").status_code == 404  # off by default
    s = settings(tmp_path, test_chat=True, db_path=str(tmp_path / "c.db"))
    app = create_app(s, anthropic_client=FakeAnthropic(reply="Limited company or sole trader?"),
                     twilio_client=FakeTwilio(), mail=FakeMail([]), validator=RequestValidator(TOKEN))
    with TestClient(app) as c:
        assert c.get("/chat").status_code == 200
        r = c.post("/api/chat", json={"session": "a1", "channel": "whatsapp", "phone": "07700 900000",
                                      "message": "I run a takeaway"}).json()
    assert r == {"reply": "Limited company or sole trader?", "needs_human": False}
