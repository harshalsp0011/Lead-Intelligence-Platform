# Outreach Agent Files

This folder contains the email sending logic used after drafts are created and approved for delivery.

## Files

email_sender.py
Sends one email draft through the configured provider, enforces daily sending limits,
appends unsubscribe footer text, and logs send events in outreach history.

Main functions:
- send_email(draft_id, db_session)
- send_via_sendgrid(to_email, to_name, subject, body, from_email)
- send_via_instantly(to_email, to_name, subject, body)
- select_provider()
- add_unsubscribe_footer(email_body)
- check_daily_limit(db_session)
- log_send_event(company_id, contact_id, draft_id, message_id, db_session)

followup_scheduler.py
Creates and manages follow-up sequence events (day 3/7/14 by default),
fetches due follow-ups, and handles cancellation/status checks.

Main functions:
- schedule_followups(company_id, contact_id, draft_id, send_date, db_session)
- get_due_followups(db_session)
- cancel_followups(company_id, db_session)
- check_sequence_status(company_id, db_session)
- mark_sequence_complete(company_id, db_session)

sequence_manager.py
Builds follow-up email subject/body content from original drafts,
loads day-specific follow-up templates, fills placeholders, and applies LLM polish.

Main functions:
- build_followup_email(original_draft_id, follow_up_number, db_session)
- get_followup_template(follow_up_number)
- build_followup_subject(original_subject, follow_up_number)

outreach_agent.py
Coordinates outreach queue operations for approved drafts and due follow-ups.

Main functions:
- process_followup_queue(db_session)
- get_approved_queue(db_session)
- check_daily_limit(db_session)
- log_outreach_run(sent_count, skipped_count, followup_count)

## Required Settings

From config/settings.py:
- EMAIL_PROVIDER
- SENDGRID_API_KEY
- SENDGRID_FROM_EMAIL
- INSTANTLY_API_KEY (if using Instantly)
- INSTANTLY_CAMPAIGN_ID (if using Instantly)
- INSTANTLY_API_BASE_URL (optional override for Instantly API host)
- INSTANTLY_REQUEST_TIMEOUT_SECONDS
- EMAIL_DAILY_LIMIT
- TB_BRAND_NAME
- TB_OFFICE_LOCATION
- UNSUBSCRIBE_INSTRUCTION

## Database Dependencies

The sender and follow-up scheduler read/write these ORM-backed tables:
- email_drafts
- contacts
- outreach_events
- companies

## Send Flow

1. Load draft and contact records.
2. Skip unsubscribed contacts.
3. Enforce daily send cap.
4. Append unsubscribe footer.
5. Send via configured provider.
6. Log sent event with follow_up_number = 0.

## Follow-up Flow

1. After successful send, call `schedule_followups(...)`.
2. A daily job calls `get_due_followups(...)` to collect follow-ups due today.
3. For each due follow-up, call `build_followup_email(...)` to create the next message.
4. Send the follow-up using `email_sender.send_email(...)` and mark queue event as `followup_sent`.
5. If a company replies, call `cancel_followups(...)`.
6. Use `check_sequence_status(...)` for reporting and progression checks.
7. If all attempts are done with no reply, call `mark_sequence_complete(...)`.

## Queue Helpers

- `get_approved_queue(...)` returns approved unsent drafts (oldest first).
- `check_daily_limit(...)` returns `{within_limit, sent_today, remaining}`.
- `log_outreach_run(...)` prints a compact run summary block.

## Notes

- The send_email function returns a compact result dict:
  - success: true/false
  - message_id: provider message id or error/skip reason
- Instantly flow reads campaign/base URL/timeout settings from `config.settings`.
- Follow-up intervals are configured centrally through `FOLLOWUP_DAY_3`, `FOLLOWUP_DAY_7`, and `FOLLOWUP_DAY_14`.

## Container

- Dockerfile: `agents/outreach/Dockerfile`
- Service name in compose: `outreach`
- Container command: `python agents/outreach/outreach_agent.py`
