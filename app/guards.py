"""Stops automatic replies to robots, newsletters, ourselves, and runaway loops."""
import re

NO_REPLY_SENDER = re.compile(
    r"(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce|notifications?@|alerts?@)", re.I
)


def email_should_skip(sender: str, mailbox: str, headers: dict[str, str]) -> str | None:
    """Return a reason to skip, or None if it's safe to auto-reply."""
    h = {k.lower(): (v or "").lower() for k, v in headers.items()}
    s = (sender or "").lower()
    if not s or "@" not in s:
        return "no sender"
    if mailbox and s == mailbox.lower():
        return "from ourselves"
    if NO_REPLY_SENDER.search(s):
        return "no-reply sender"
    if h.get("auto-submitted", "no") not in ("", "no"):
        return "auto-submitted"
    if h.get("precedence", "") in ("bulk", "list", "junk", "auto_reply"):
        return "bulk/list"
    if "list-unsubscribe" in h or "list-id" in h:
        return "mailing list"
    if "x-autoreply" in h or "x-autorespond" in h:
        return "auto-reply"
    if "all" in h.get("x-auto-response-suppress", "") or "oof" in h.get("x-auto-response-suppress", ""):
        return "auto-response suppressed"
    return None


def mask(contact: str) -> str:
    """For logs: show enough to identify, not the full address/number."""
    c = contact or ""
    if "@" in c:
        name, _, domain = c.partition("@")
        return f"{name[:2]}***@{domain}"
    return f"***{c[-4:]}"
