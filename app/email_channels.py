"""Email in/out. Microsoft 365 (Graph, the target) and IMAP/SMTP (IONOS, during migration)."""
import asyncio
import email
import email.utils
import html
import imaplib
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class Incoming:
    key: str            # unique id for de-duplication
    sender: str
    sender_name: str
    subject: str
    text: str
    headers: dict = field(default_factory=dict)
    ref: object = None  # provider-specific handle (Graph id, or the parsed message)


QUOTE_START = re.compile(r"^(On .+wrote:|-----Original Message-----|From: .+|Sent from my )", re.I)


def strip_quoted(text: str) -> str:
    """Keep only the new part of an email reply."""
    out = []
    for line in (text or "").splitlines():
        if QUOTE_START.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()[:6000]


def text_to_html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw or "")
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


# ---------------------------------------------------------------- Microsoft 365
class GraphMail:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, mailbox: str, http=None):
        self.mailbox = mailbox
        self._http = http or httpx.AsyncClient(timeout=30)
        self._app = None
        if client_id:
            import msal

            self._app = msal.ConfidentialClientApplication(
                client_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                client_credential=client_secret,
            )

    async def _headers(self) -> dict:
        def token():
            r = self._app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            if "access_token" not in r:
                raise RuntimeError(f"Graph token error: {r.get('error')}")
            return r["access_token"]

        tok = await asyncio.to_thread(token) if self._app else "test-token"
        return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    async def fetch_new(self) -> list[Incoming]:
        h = await self._headers()
        h["Prefer"] = 'outlook.body-content-type="text"'
        params = {
            "$filter": "isRead eq false",
            "$top": "20",
            "$select": "id,subject,from,uniqueBody,body,internetMessageHeaders,receivedDateTime",
        }
        r = await self._http.get(f"{GRAPH}/users/{self.mailbox}/mailFolders/inbox/messages", headers=h, params=params)
        r.raise_for_status()
        items = sorted(r.json().get("value", []), key=lambda m: m.get("receivedDateTime", ""))
        out = []
        for m in items:
            addr = (m.get("from") or {}).get("emailAddress") or {}
            body = (m.get("uniqueBody") or m.get("body") or {}).get("content", "")
            headers = {x["name"]: x["value"] for x in (m.get("internetMessageHeaders") or [])}
            out.append(Incoming(
                key=f"graph:{m['id']}", sender=addr.get("address", ""), sender_name=addr.get("name", ""),
                subject=m.get("subject") or "", text=strip_quoted(body), headers=headers, ref=m["id"],
            ))
        return out

    async def reply(self, msg: Incoming, text: str) -> None:
        r = await self._http.post(
            f"{GRAPH}/users/{self.mailbox}/messages/{msg.ref}/reply",
            headers=await self._headers(), json={"comment": text_to_html(text)},
        )
        r.raise_for_status()

    async def mark_done(self, msg: Incoming) -> None:
        r = await self._http.patch(
            f"{GRAPH}/users/{self.mailbox}/messages/{msg.ref}", headers=await self._headers(), json={"isRead": True}
        )
        r.raise_for_status()

    async def send(self, to: str, subject: str, text: str) -> None:
        body = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": text},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        r = await self._http.post(f"{GRAPH}/users/{self.mailbox}/sendMail", headers=await self._headers(), json=body)
        r.raise_for_status()


# ---------------------------------------------------------------- IMAP / SMTP (IONOS)
class ImapMail:
    def __init__(self, imap_host, imap_port, smtp_host, smtp_port, mailbox, password):
        self.imap_host, self.imap_port = imap_host, imap_port
        self.smtp_host, self.smtp_port = smtp_host, smtp_port
        self.mailbox, self.password = mailbox, password

    def _fetch(self) -> list[Incoming]:
        out = []
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as imap:
            imap.login(self.mailbox, self.password)
            imap.select("INBOX")
            _, data = imap.uid("search", None, "UNSEEN")
            for uid in (data[0] or b"").split()[:20]:
                _, parts = imap.uid("fetch", uid, "(BODY.PEEK[])")  # PEEK: don't mark read yet
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if not raw:
                    continue
                m = email.message_from_bytes(raw)
                name, addr = email.utils.parseaddr(m.get("From", ""))
                text = ""
                part = m.get_body(preferencelist=("plain", "html")) if hasattr(m, "get_body") else None
                if part is None and not m.is_multipart():
                    part = m
                if part is not None:
                    payload = part.get_payload(decode=True) or b""
                    text = payload.decode(part.get_content_charset() or "utf-8", "replace")
                    if part.get_content_type() == "text/html":
                        text = html_to_text(text)
                msg_id = m.get("Message-ID", "") or f"uid-{uid.decode()}"
                out.append(Incoming(
                    key=f"imap:{msg_id}", sender=addr, sender_name=name, subject=str(m.get("Subject", "")),
                    text=strip_quoted(text), headers={k: str(v) for k, v in m.items()},
                    ref={"uid": uid, "message_id": msg_id, "references": m.get("References", "")},
                ))
        return out

    def _smtp_send(self, em: EmailMessage) -> None:
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ssl.create_default_context()) as s:
            s.login(self.mailbox, self.password)
            s.send_message(em)

    def _mark_seen(self, uid) -> None:
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as imap:
            imap.login(self.mailbox, self.password)
            imap.select("INBOX")
            imap.uid("store", uid, "+FLAGS", "(\\Seen)")

    async def fetch_new(self) -> list[Incoming]:
        return await asyncio.to_thread(self._fetch)

    async def reply(self, msg: Incoming, text: str) -> None:
        em = EmailMessage()
        em["From"], em["To"] = self.mailbox, msg.sender
        subj = msg.subject or ""
        em["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
        em["In-Reply-To"] = msg.ref["message_id"]
        em["References"] = (msg.ref["references"] + " " + msg.ref["message_id"]).strip()
        em["Auto-Submitted"] = "auto-replied"  # tells other robots not to answer us (RFC 3834)
        em.set_content(text)
        await asyncio.to_thread(self._smtp_send, em)

    async def mark_done(self, msg: Incoming) -> None:
        await asyncio.to_thread(self._mark_seen, msg.ref["uid"])

    async def send(self, to: str, subject: str, text: str) -> None:
        em = EmailMessage()
        em["From"], em["To"], em["Subject"] = self.mailbox, to, subject
        em.set_content(text)
        await asyncio.to_thread(self._smtp_send, em)
