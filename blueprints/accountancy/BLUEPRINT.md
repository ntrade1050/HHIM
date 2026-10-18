# Accountancy Blueprint: AI front desk for UK accountancy firms

Built from the first live client, H.HIM Chartered Accounting & Tax Services (October 2026).
Use this for any accountancy or tax practice. Update it every time a client teaches us something. Status markers:
- **[proven]**: worked live with a client.
- **[built]**: tested with dummy data only, not yet live.
- **[todo]**: not done yet.

## 1. What the client gets
- **[built] WhatsApp assistant.** Answers new enquiries 24/7, using only the firm's own information.
- **[built] Short, smart replies.** WhatsApp replies are under 25 words. Each reply answers the point, then asks the ONE question that matters for that service:
  - tax return → self-employed, landlord or both?
  - accounts → limited company or sole trader?
  - payroll → how many staff?
  - VAT → already registered?
- **[built] Books the free consultation inside the chat.**
  - Offers 3 real free times, takes the client's choice and name, and books it.
  - The same slot can't be booked twice.
  - There's also a web booking page.
- **[built] SMS.** A confirmation text for web bookings, a text to the owner for every booking and every "needs a person" enquiry, and a reminder text the day before.
- **[built] Safety.**
  - Never quotes prices; it's a fixed fee after the free consultation.
  - Never gives advice specific to the client's situation.
  - HMRC letters, penalties, deadlines and complaints mean "book the earliest slot with an accountant", and the owner is alerted.
  - Never promises a call-back; the next step is always booking.
- **[built] Test / live switch.** In `BOT_MODE=test` the bot only answers the owner's test numbers, and everyone else's messages are texted to the owner.
- **[built] Choice of AI model.** Claude (default) or DeepSeek, OpenAI or OpenRouter, changed with one setting.
- **[built, off] Email replies.** Email works with Microsoft 365 or IMAP, but stays off until the client's mailbox is stable. H.HIM was mid-move from IONOS to Microsoft 365.

## 2. Accounts the client opens (all in the client's name, us added as admin)
| What | Where | Notes |
|---|---|---|
| Twilio | https://www.twilio.com/try-twilio | Card on file. WhatsApp sender plus SMS sender ("FIRMNAME", max 11 characters) |
| Meta Business + verification | https://business.facebook.com | **Start on day 1.** Free, but can take weeks. Needed before WhatsApp goes live |
| WhatsApp number | — | Use a NEW number for the bot. A number on the WhatsApp Business app must be removed from the app before Twilio can use it |
| Server (VPS) | OVHcloud (H.HIM's choice) or DigitalOcean | Smallest plan, UK data centre if offered, backups on |
| AI key | https://platform.claude.com or https://platform.deepseek.com | Set a monthly spend limit |
| Uptime alert (optional) | https://uptimerobot.com | Free. Watches `/health` |

Typical running cost at about 300 enquiries a month is roughly $25–30 a month, mostly Twilio's $0.005 per message. Re-check Twilio and Meta prices for each client; Meta announced WhatsApp pricing changes for October 2026.

## 3. Questions to ask the owner (before setup)
1. Opening hours and consultation length. These set the booking slots: `BOOKING_DAYS`, `BOOKING_START`, `BOOKING_END`, `SLOT_MINUTES`.
2. Office addresses, main phone number and email.
3. Services and sectors they want to win, and any they don't do.
4. Pricing stance: "fixed fee after free consultation" (the default), or guide prices they're happy to publish.
5. Professional body (ICAEW / ACCA / other) and software they use (Xero, QuickBooks…). Clients ask about both.
6. Owner's mobile for alerts, and who else should test.
7. Which WhatsApp number: a new number (recommended) or their existing one?
8. Their top 10–20 enquiry questions and how they answer them. Better still, an export of past enquiries.

## 4. Setup order
1. Day 1: the client starts Meta business verification and opens Twilio. Start this first because it's the slow step.
2. Fill `knowledge/<firm>.md` from `knowledge-template.md` and the owner's answers. Read their website, but confirm every fact with the owner.
3. Set up the server and fill in `.env` (start from `.env.example`). Use `BOT_MODE=test`, put the owner and testers in `TEST_NUMBERS`, and leave `EMAIL_PROVIDER=off`.
4. Test on the Twilio sandbox, then on the real number once Meta approves.
5. Owner testing: try the scripts in section 5 until they're happy.
6. Sign-off, then switch `BOT_MODE=live`.
7. Week 1 live: read the conversations and refine the knowledge file. The rules rarely need changing.

## 5. Owner test script (run in test mode)
- "How much do you charge for a tax return?" → no price; asks self-employed / landlord.
- "I run a takeaway, can you help?" → asks limited company or sole trader.
- "Can I book a call?" → offers 3 times; pick one, give name → confirmed in chat; owner gets a text.
- "I've had a penalty letter from HMRC" → books earliest slot; owner gets "needs a person" text.
- Ask something not in the knowledge (e.g. "Do you do audits for PLCs?") → no invented answer; offers consultation.
- A message from a number NOT in `TEST_NUMBERS` → no bot reply; owner gets a text.
- The day before a test booking → reminder text arrives.

## 6. Lessons from H.HIM
- Replies must be very short. Long, list-style answers were rejected straight away, and limiting replies to one question each fixed it.
- Never say "we'll call you". The owner wants every conversation to end in a calendar booking.
- Clients may be mid-migration (e.g. email). Launch on WhatsApp and SMS first and add email later, so one channel doesn't block the others.
- The owner wants to test privately before opening to the public, hence test mode.
- The client owns everything (Twilio, server, keys) so the system is independent of us.
- Website facts can be wrong. H.HIM's site showed two different phone numbers, so confirm facts with the owner.

## 7. [todo] Next improvements
- Rules per industry: move the accountancy-specific prompt rules into this blueprint folder, so a solicitors blueprint can sit beside it without code changes.
- Deploy kit: Docker, Caddy HTTPS, nightly backup and a server guide.
- Store the parts of the prompt that never change with the AI provider, so they're charged at a lower rate.
- Connect bookings to Microsoft Bookings or Outlook once the client's Microsoft 365 is ready.
- Onboarding steps after booking: ID/anti-money-laundering checks, engagement letter, and the request to the client's previous accountant.
