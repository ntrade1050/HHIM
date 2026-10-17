"""FastAPI app: WhatsApp webhook + background email poller."""
import asyncio
import contextlib
import logging
import re

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from .book_page import render as render_book_page
from .chat_page import render as render_chat_page
from .booking import BookingError, BookingRules, BookingService
from .brain import Brain
from .config import get_settings, load_env_file
from .email_channels import GraphMail, ImapMail
from .guards import email_should_skip, mask
from .llm import build_llm
from .sms import Sms
from .service import ReplyService
from .store import Store

log = logging.getLogger("reply_desk")
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
WHATSAPP_LIMIT = 1500  # Twilio caps a message body at 1600 characters


def build_email(s):
    if s.email_provider == "m365":
        return GraphMail(s.m365_tenant_id, s.m365_client_id, s.m365_client_secret, s.mailbox)
    if s.email_provider == "imap":
        return ImapMail(s.imap_host, s.imap_port, s.smtp_host, s.smtp_port, s.mailbox, s.email_password)
    return None


async def poll_email_once(service: ReplyService, mail, s) -> int:
    handled = 0
    for msg in await mail.fetch_new():
        if not service.store.claim(msg.key):
            continue
        reason = email_should_skip(msg.sender, s.mailbox, msg.headers)
        if reason or not msg.text.strip():
            log.info("email skipped (%s) from=%s", reason or "empty", mask(msg.sender))
            with contextlib.suppress(Exception):
                await mail.mark_done(msg)
            continue
        text = f"Subject: {msg.subject}\n\n{msg.text}" if msg.subject else msg.text
        label = f"{msg.sender_name} <{msg.sender}>".strip()

        async def send(reply, m=msg):
            await mail.reply(m, reply)

        try:
            await service.handle("email", msg.sender.lower(), text, send, label)
            handled += 1
        except Exception:
            log.exception("email reply failed from=%s", mask(msg.sender))
        with contextlib.suppress(Exception):
            await mail.mark_done(msg)
    return handled


async def email_loop(service, mail, s):
    while True:
        try:
            await poll_email_once(service, mail, s)
        except Exception:
            log.exception("email poll failed")
        await asyncio.sleep(s.poll_seconds)


def create_app(settings=None, anthropic_client=None, twilio_client=None, mail=None, validator=None,
               now=None, llm=None) -> FastAPI:
    if settings is None:
        load_env_file()
        settings = get_settings()
    s = settings
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if llm is None:
        llm = build_llm(s, anthropic_client)
    if twilio_client is None and s.twilio_account_sid:
        from twilio.rest import Client

        twilio_client = Client(s.twilio_account_sid, s.twilio_auth_token)
    if validator is None and s.twilio_auth_token:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(s.twilio_auth_token)
    if mail is None:
        mail = build_email(s)

    store = Store(s.db_path)
    brain = Brain(llm, s.business_name, s.knowledge_dir, s.booking_url)

    sms = Sms(twilio_client, s.sms_from, dry_run=s.dry_run)

    async def notify(subject, text):
        """Tell the owner: SMS to OWNER_PHONE and/or email to HANDOFF_EMAIL, whichever is set up."""
        if s.owner_phone:
            await sms.send(s.owner_phone, f"{subject[:120]}\n{text.split('Their message:')[-1].strip()[:300]}")
        if mail and s.handoff_email:
            await mail.send(s.handoff_email, subject, text)

    rules = BookingRules(tz=s.timezone, days=s.booking_days, start=s.booking_start, end=s.booking_end,
                         minutes=s.slot_minutes, days_ahead=s.booking_days_ahead)
    bookings = BookingService(store, mail, rules, s.business_name, s.owner_email, s.mailbox, dry_run=s.dry_run,
                              sms=sms, owner_phone=s.owner_phone, **({"now": now} if now else {}))
    brain.ask_email = bookings.wants_email
    service = ReplyService(store, brain, s, notify, bookings)

    async def reminder_loop():
        while True:
            try:
                n = await bookings.send_due_reminders(s.reminder_hours)
                if n:
                    log.info("sent %d reminder(s)", n)
            except Exception:
                log.exception("reminders failed")
            await asyncio.sleep(300)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        tasks = []
        if mail and s.poll_seconds > 0:
            tasks.append(asyncio.create_task(email_loop(service, mail, s)))
        if s.reminder_hours > 0 and sms.ready:
            tasks.append(asyncio.create_task(reminder_loop()))
        log.info("Reply desk started: email=%s sms=%s dry_run=%s auto_reply=%s", s.email_provider, sms.ready,
                 s.dry_run, s.auto_reply)
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title="Reply Desk", lifespan=lifespan)
    app.state.service = service
    app.state.bookings = bookings

    @app.get("/book", response_class=HTMLResponse)
    async def book_page():
        return render_book_page(s.business_name, s.slot_minutes, ask_email=bookings.wants_email)

    @app.get("/api/slots")
    async def slots():
        return {"slots": bookings.free_slots()}

    @app.post("/api/book")
    async def book(request: Request):
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return JSONResponse({"error": "Please choose a time and fill in your details."}, status_code=400)
        try:
            result = await bookings.book(str(data.get("start") or ""), str(data.get("name") or ""),
                                         str(data.get("email") or ""), str(data.get("phone") or ""),
                                         str(data.get("note") or ""))
        except BookingError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        log.info("booking %s at %s for %s emailed=%s", result["id"], result["start"], mask(result["email"]),
                 result["emailed"])
        return {"when": result["when"], "id": result["id"]}

    if s.test_chat:
        model_label = s.model if s.llm_provider == "anthropic" else f"{s.llm_provider}: {getattr(llm, 'model', '')}"

        @app.get("/chat", response_class=HTMLResponse)
        async def chat_page():
            return render_chat_page(s.business_name, model_label)

        @app.post("/api/chat")
        async def chat(request: Request):
            data = await request.json()
            channel = "email" if data.get("channel") == "email" else "whatsapp"
            message = str(data.get("message") or "").strip()[:4000]
            if not message:
                return JSONResponse({"error": "Type a message first."}, status_code=400)
            session = re.sub(r"[^a-z0-9]", "", str(data.get("session") or ""))[:20] or "x"
            phone = re.sub(r"[^\d+]", "", str(data.get("phone") or ""))
            contact = f"whatsapp:{phone}#{session}" if channel == "whatsapp" else f"test-{session}@example.com"

            async def send(_reply):
                return None  # the page shows the reply; nothing goes to WhatsApp or email

            outcome = await service.handle(channel, contact, message, send, f"Test chat {session}")
            last = (store.history(channel, contact, 1) or [{}])[-1]
            reply = last.get("content", "") if last.get("role") == "assistant" else f"(no reply: {outcome})"
            last_answer = service.last_answer.get((channel, contact))
            return {"reply": reply, "needs_human": bool(last_answer and last_answer.needs_human)}

    @app.get("/health")
    async def health():
        return {"ok": True, "email": s.email_provider, "dry_run": s.dry_run, "auto_reply": s.auto_reply}

    @app.post("/whatsapp")
    async def whatsapp(request: Request, background: BackgroundTasks):
        form = dict(await request.form())
        url = f"{s.public_base_url}/whatsapp" if s.public_base_url else str(request.url)
        if not validator or not validator.validate(url, form, request.headers.get("X-Twilio-Signature", "")):
            return Response(status_code=403)
        sid, sender, body = form.get("MessageSid", ""), form.get("From", ""), (form.get("Body") or "").strip()
        if sid and store.claim(f"wa:{sid}") and sender and body:
            background.add_task(_whatsapp_reply, service, twilio_client, s, sender, body[:4000],
                                form.get("ProfileName", ""))
        # Reply to Twilio straight away; the real answer is sent separately so we never hit its timeout.
        return Response(EMPTY_TWIML, media_type="application/xml")

    return app


async def _whatsapp_reply(service, twilio_client, s, sender, body, name):
    async def send(reply):
        for i in range(0, len(reply), WHATSAPP_LIMIT):
            await asyncio.to_thread(
                twilio_client.messages.create, from_=s.twilio_whatsapp_from, to=sender, body=reply[i:i + WHATSAPP_LIMIT]
            )

    try:
        await service.handle("whatsapp", sender, body, send, f"{name} ({sender})".strip())
    except Exception:
        log.exception("whatsapp reply failed contact=%s", mask(sender))


def get_app():
    """Run with: uvicorn app.main:get_app --factory"""
    return create_app()
