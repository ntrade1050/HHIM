# H.HIM Reply Desk: handoff (18 Oct 2026)

**Client:** H.HIM Chartered Accounting & Tax Services (hhim.co.uk). Owner: Imran Maqsood.
**Builder:** NR / Synergy AI.
**Repo:** https://github.com/ntrade1050/HHIM (private).
- `main` = v0.4.
- **`spike/sms-whatsapp`** = latest work. Not merged yet; merge after the owner signs off in test mode.

## What it is
An AI front desk for WhatsApp, with SMS, for an accountancy firm.
- Answers enquiries using only `knowledge/hhim.md`.
- Gives short replies (WhatsApp ≤25 words) and asks one qualifying question per service.
- Books free consultations inside the chat: offers 3 real free slots and takes the client's choice and name. There is also a web page at `/book`, and the same slot can't be booked twice.
- SMS:
  - a confirmation for web bookings;
  - a text to the owner for every booking and every enquiry handed to a person;
  - a reminder the day before.
- Never quotes prices and never says "we'll call you". HMRC letters, penalties and complaints mean "book the earliest slot", and the owner is alerted.
- **Test/live switch:** `BOT_MODE=test` answers only `TEST_NUMBERS`; everyone else's messages are texted to `OWNER_PHONE`. `BOT_MODE=live` answers everyone.
- **AI model is swappable:** `LLM_PROVIDER=anthropic` (default, Claude Haiku 4.5), `deepseek` (deepseek-flash / deepseek-v4-pro), `openai`, `openrouter`, `openai_compatible`.
- **Email** (Microsoft 365 Graph or IMAP/SMTP) is built but **OFF**: the client is moving from IONOS to Microsoft 365. Use `EMAIL_PROVIDER=off`.
- **Local test chat:** set `TEST_CHAT=true` and open http://localhost:8000/chat.
- **Tests:** 41 passing, all with dummy data (`python -m pytest -q`). **Nothing has run live yet.**

## Code map (`app/`)
- `main.py`: routes `/whatsapp` (Twilio webhook, signature-checked), `/book`, `/api/slots`, `/api/book`, `/chat`, `/health`, plus the reminder loop.
- `brain.py`: prompt rules and the reply schema, including the `book` field for in-chat booking.
- `llm.py`: AI providers.
- `service.py`: the flow: remember → answer → book → send → alert the owner.
- `booking.py`: slots, bookings, calendar invites, SMS confirmations, reminders.
- `sms.py`: SMS sending; tidies UK numbers to +44.
- `store.py`: the SQLite database.
- `guards.py`: email loop protection and masking numbers in logs.
- `config.py`: all settings (see `.env.example`).
- `blueprints/accountancy/`: **the reusable blueprint** for future accountant clients (`BLUEPRINT.md` plus `knowledge-template.md`).

## Decisions made
- **Today's scope:** WhatsApp and SMS only. No IONOS and no email until the Microsoft 365 move is done.
- Everything goes in the **client's name**: Twilio, server, AI key. NR is added as admin.
- **Server:** OVHcloud VPS (owner's choice). Use the server's own address for now; `desk.hhim.co.uk` comes later.
- Send confirmations on the channel they booked through: WhatsApp bookings are confirmed in the chat, web bookings by SMS.
- Reminders go by SMS, because WhatsApp messages the business starts need templates pre-approved by Meta.
- The owner tests in `BOT_MODE=test` before going live.

## What H.HIM needs (WhatsApp and SMS only)
1. Twilio account, with a card added: https://www.twilio.com/try-twilio
2. A WhatsApp number for the bot. A new number is recommended; an existing WhatsApp Business app number must be removed from the app first.
3. Meta Business account plus business verification: https://business.facebook.com. Free, but can take weeks, so start first.
4. SMS sender ("HHIM", or a Twilio UK number), set up inside Twilio.
5. OVHcloud VPS: https://www.ovhcloud.com/en-gb/vps/
6. AI key: https://platform.claude.com or https://platform.deepseek.com, with a spend limit set.
7. The owner's mobile number, plus the numbers of anyone else testing.
8. From Imran:
   - opening hours (these set the booking slots);
   - the correct phone number (the site shows both 0333 224 9380 and 0333 223 9380);
   - the Blackburn address;
   - whether to give guide prices;
   - his professional body and accounting software;
   - his top questions from clients.
9. Optional: an uptime alert at https://uptimerobot.com

**Cost** at about 300 enquiries a month is roughly $25–30 a month. Twilio charges $0.005 for every message in and out, Meta's reply fee is unconfirmed (check the October 2026 change), a UK number is $2.50 a month, the server is about $6, and AI is about $1–4.

## Next steps
1. **Deploy kit** in the repo, about 1 hour: Dockerfile, docker-compose (restart always), Caddy HTTPS, nightly SQLite backup, OVHcloud server guide.
2. Fill in `knowledge/hhim.md` with Imran's answers. Lines marked `[CONFIRM]` are still open.
3. Set up the server with `BOT_MODE=test`, run the owner test script (BLUEPRINT.md section 5), get sign-off, merge `spike/sms-whatsapp` into `main`, then set `BOT_MODE=live`.
4. Later:
   - store the prompt parts that never change, so they're charged at a lower rate;
   - move accountancy rules into the blueprint (for a solicitors blueprint);
   - connect to Microsoft Bookings/Outlook after the Microsoft 365 move;
   - switch email on;
   - onboarding steps: ID/AML checks and the engagement letter.

## Security notes
- Never commit `.env`; it is git-ignored. Keys go only into `.env` on the server.
- A DeepSeek key was pasted into chat on 17 Oct. **Delete it and make a new one** in the DeepSeek dashboard.
- Twilio webhook requests are signature-checked, and phone numbers are masked in logs.

## Test page (built in Claude)
The "H.HIM Reply Desk Test" page in your Claude artifacts is the role-play chat with an example calendar. It runs on Claude, separately from this code.
