# Reply Desk

Answers new enquiries automatically on **WhatsApp** (Twilio) and **email** (Microsoft 365, or IONOS while the
migration finishes), using Claude Haiku and only the business information in `knowledge/`.

## What it does
- Replies in the right style for each channel and remembers each person's conversation.
- Answers only from `knowledge/*.md`. Edit those files and the change applies to the very next reply.
- Hands over to a person: if the answer isn't known, the customer is upset or it needs real advice, it sends a polite holding reply and emails `HANDOFF_EMAIL`.
- Safety:
  - Never replies to no-reply senders, newsletters, auto-replies or itself.
  - Stops at 20 replies per person per day, so two robots can't loop.
  - Handles each message once, even if Twilio retries.
  - Rejects WhatsApp requests that aren't signed by Twilio.
  - `DRY_RUN=true` logs replies without sending anything.

## Booking
- On WhatsApp and email, the bot offers 3 real free times. The client picks one and gives their name and email, and it books in the chat.
- Clients can also pick any time at `PUBLIC_BASE_URL/book`.
- Every booking emails a confirmation with a calendar invite to the client and to `OWNER_EMAIL`.
- The same slot can never be booked twice.

## Switching AI model
Claude is the default. To use DeepSeek, set `LLM_PROVIDER=deepseek` and `LLM_API_KEY`. The default model is `deepseek-flash`; set `LLM_MODEL=deepseek-v4-pro` for the bigger one. `openai`, `openrouter` and any `openai_compatible` API work the same way: see `.env.example`.
If a model fails or returns nothing, the client still gets a polite booking-link reply.

## Run it on Windows (PowerShell)
```powershell
cd reply-desk
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env    # then fill it in
python -m pytest -q       # 39 tests, all fakes, no cost
uvicorn app.main:get_app --factory --port 8000
```
Open http://localhost:8000/health to check it's running.

## WhatsApp (Twilio sandbox)
1. Give the service a public address. Run `ngrok http 8000` and put the https address in `PUBLIC_BASE_URL`, then restart uvicorn.
2. In the Twilio Console, go to Messaging → Try it out → Send a WhatsApp message → Sandbox settings. Under "When a message comes in", enter `PUBLIC_BASE_URL/whatsapp` with method POST, then save.
3. Copy the Account SID and Auth Token into `.env`.

## Email now: IONOS
Set `EMAIL_PROVIDER=imap`, `MAILBOX=info@hhim.co.uk` and `EMAIL_PASSWORD` (the mailbox password).
The service checks for unread mail every 30 seconds, replies in the same thread, then marks the email read.

## Email after the move: Microsoft 365
1. In the Entra admin centre, go to App registrations → New registration, name it "Reply Desk" and register.
2. Under API permissions, add Microsoft Graph application permissions **Mail.ReadWrite** and **Mail.Send**, then click **Grant admin consent**.
3. Under Certificates & secrets, add a new client secret.
4. Fill in `M365_TENANT_ID`, `M365_CLIENT_ID` and `M365_CLIENT_SECRET`, set `EMAIL_PROVIDER=m365`, then restart.
5. Recommended: limit the app to the one mailbox using Exchange Online "RBAC for Applications".

## Going live
Test with `DRY_RUN=true` first and read the log. Then set `DRY_RUN=false`.
