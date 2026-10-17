"""FastAPI app: WhatsApp webhook + background email poller."""
import asyncio
import contextlib
import logging

from fastapi import BackgroundTasks, FastAPI, Request, Response

from .brain import Brain
from .config import get_settings, load_env_file
from .email_channels import GraphMail, ImapMail
from .guards import email_should_skip, mask
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


def create_app(settings=None, anthropic_client=None, twilio_client=None, mail=None, validator=None) -> FastAPI:
    if settings is None:
        load_env_file()
        settings = get_settings()
    s = settings
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if anthropic_client is None:
        import anthropic

        anthropic_client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key)
    if twilio_client is None and s.twilio_account_sid:
        from twilio.rest import Client

        twilio_client = Client(s.twilio_account_sid, s.twilio_auth_token)
    if validator is None and s.twilio_auth_token:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(s.twilio_auth_token)
    if mail is None:
        mail = build_email(s)

    store = Store(s.db_path)
    brain = Brain(anthropic_client, s.model, s.business_name, s.knowledge_dir)

    async def notify(subject, text):
        if mail:
            await mail.send(s.handoff_email, subject, text)

    service = ReplyService(store, brain, s, notify)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(email_loop(service, mail, s)) if mail and s.poll_seconds > 0 else None
        log.info("Reply desk started: email=%s dry_run=%s auto_reply=%s", s.email_provider, s.dry_run, s.auto_reply)
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Reply Desk", lifespan=lifespan)
    app.state.service = service

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
