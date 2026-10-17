"""Settings, read once from environment variables (or a local .env file)."""
import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    business_name: str
    knowledge_dir: str
    db_path: str
    dry_run: bool
    auto_reply: bool
    max_replies_per_contact_per_day: int
    handoff_email: str
    test_chat: bool
    booking_url: str
    owner_email: str
    timezone: str
    booking_days: str
    booking_start: str
    booking_end: str
    slot_minutes: int
    booking_days_ahead: int
    # Claude
    anthropic_api_key: str
    model: str
    llm_provider: str   # anthropic | deepseek | openai | openrouter | openai_compatible
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    # WhatsApp (Twilio)
    public_base_url: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str
    # Email
    email_provider: str  # "m365" | "imap" | "off"
    mailbox: str
    poll_seconds: int
    m365_tenant_id: str
    m365_client_id: str
    m365_client_secret: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    email_password: str


def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        business_name=e("BUSINESS_NAME", "Our team"),
        knowledge_dir=e("KNOWLEDGE_DIR", "knowledge"),
        db_path=e("DB_PATH", "reply_desk.db"),
        dry_run=_bool("DRY_RUN", True),
        auto_reply=_bool("AUTO_REPLY", True),
        max_replies_per_contact_per_day=int(e("MAX_REPLIES_PER_CONTACT_PER_DAY", "20")),
        handoff_email=e("HANDOFF_EMAIL", ""),
        test_chat=_bool("TEST_CHAT", False),
        booking_url=e("BOOKING_URL", "") or (e("PUBLIC_BASE_URL", "").rstrip("/") + "/book" if e("PUBLIC_BASE_URL") else ""),
        owner_email=e("OWNER_EMAIL", "") or e("HANDOFF_EMAIL", ""),
        timezone=e("TIMEZONE", "Europe/London"),
        booking_days=e("BOOKING_DAYS", "mon,tue,wed,thu,fri"),
        booking_start=e("BOOKING_START", "09:30"),
        booking_end=e("BOOKING_END", "17:00"),
        slot_minutes=int(e("SLOT_MINUTES", "30")),
        booking_days_ahead=int(e("BOOKING_DAYS_AHEAD", "10")),
        anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
        model=e("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        llm_provider=e("LLM_PROVIDER", "anthropic").lower(),
        llm_base_url=e("LLM_BASE_URL", ""),
        llm_api_key=e("LLM_API_KEY", ""),
        llm_model=e("LLM_MODEL", ""),
        public_base_url=e("PUBLIC_BASE_URL", "").rstrip("/"),
        twilio_account_sid=e("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=e("TWILIO_AUTH_TOKEN", ""),
        twilio_whatsapp_from=e("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"),
        email_provider=e("EMAIL_PROVIDER", "off").lower(),
        mailbox=e("MAILBOX", ""),
        poll_seconds=int(e("POLL_SECONDS", "30")),
        m365_tenant_id=e("M365_TENANT_ID", ""),
        m365_client_id=e("M365_CLIENT_ID", ""),
        m365_client_secret=e("M365_CLIENT_SECRET", ""),
        imap_host=e("IMAP_HOST", "imap.ionos.co.uk"),
        imap_port=int(e("IMAP_PORT", "993")),
        smtp_host=e("SMTP_HOST", "smtp.ionos.co.uk"),
        smtp_port=int(e("SMTP_PORT", "465")),
        email_password=e("EMAIL_PASSWORD", ""),
    )
