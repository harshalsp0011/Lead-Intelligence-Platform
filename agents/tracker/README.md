# Tracker Agent Files

This folder contains webhook handling logic for post-send email engagement events.

## Files

webhook_listener.py
Runs an HTTP webhook endpoint for SendGrid events, validates and parses payloads,
normalizes event names, extracts reply text, and forwards events to tracker processing.

Main functions:
- start_listener(port)
- receive_webhook(request)
- parse_sendgrid_event(raw_payload)
- validate_webhook(headers, body)
- extract_reply_content(sendgrid_inbound_event)

reply_classifier.py
Classifies cleaned inbound replies into sentiment and intent for automation and sales alerts.

Main functions:
- classify_reply(reply_text)
- rule_based_classify(reply_text)
- extract_reply_intent(reply_text)
- generate_reply_summary(reply_text, company_name, contact_name, sentiment)
- should_alert_sales(sentiment, intent)

alert_sender.py
Sends hot-lead alerts to Slack and email when reply signals require sales action.

Main functions:
- send_slack_alert(company_name, contact_name, contact_title, savings_formatted, score, sentiment, reply_summary)
- send_email_alert(to_email, company_name, contact_name, savings_formatted, score, sentiment, reply_summary, company_id)
- build_alert_message(company_name, contact_name, contact_title, savings_formatted, score, sentiment, reply_summary, company_id)
- should_alert(event_type, sentiment, intent)
- format_alert_timestamp()

status_updater.py
Updates company/contact lifecycle status and logs event transitions based on webhook outcomes.

Main functions:
- update_lead_status(company_id, new_status, db_session)
- mark_replied(company_id, reply_content, sentiment, db_session)
- mark_unsubscribed(contact_id, db_session)
- mark_bounced(contact_id, db_session)
- mark_opened(company_id, contact_id, db_session)
- mark_sales_alerted(outreach_event_id, db_session)

tracker_agent.py
Coordinates tracker event entrypoints and daily stuck-lead health checks.

Main functions:
- process_event(event)
- check_stuck_leads(db_session)
- resolve_stuck_lead(company_id, db_session)
- run_daily_checks(db_session)

## Required Dependencies

- fastapi
- uvicorn
- config/settings.py for SENDGRID_API_KEY
- agents/tracker/tracker_agent.py should expose process_event(event)

## Endpoint

- POST /webhooks/email

The listener always returns HTTP 200 to avoid webhook retry storms.
Invalid signature events are logged and skipped from strict blocking in phase 1.

## Event Mapping

SendGrid to internal event_type mapping:
- open -> opened
- click -> clicked
- bounce -> bounced
- unsubscribe -> unsubscribed
- inbound -> replied

## Standard Event Shape

Each parsed event is normalized into:
- event_type
- message_id
- email
- timestamp
- reply_content

## Usage

1. Start listener service with start_listener(port=8002).
2. Configure SendGrid Event Webhook URL to /webhooks/email.
3. Ensure tracker_agent.process_event(event) persists and handles event routing.
4. Classify inbound reply text with classify_reply(...) and alert sales using should_alert_sales(...).
5. Send alerts with send_slack_alert(...) and/or send_email_alert(...) when should_alert(...) returns true.
6. Update lead/contact/event state with status_updater helpers after each event is processed.
7. Run `run_daily_checks(...)` once per day to find stale leads and resolve or flag them.

## Container

- Dockerfile: `agents/tracker/Dockerfile`
- Service name in compose: `tracker`
- Container command: `python agents/tracker/tracker_agent.py`
