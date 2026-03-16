# Writer Agent Files

This folder contains the email writing helpers used after a lead is scored and a contact is selected.

## Files

`template_engine.py`
Loads template files from `data/templates/`, builds placeholder context values from company/features/score/contact records, and fills `{{placeholders}}` with real data.

Main functions:
- `load_template(industry)`: Load industry email template text.
- `load_followup_template(follow_up_number)`: Load day 3/7/14 follow-up template text.
- `fill_static_fields(template_string, context_dict)`: Replace known placeholders.
- `build_context(company, features, score, contact, settings)`: Build values used in templates.
- `get_template_for_industry(industry)`: Return template file path.

`llm_connector.py`
Handles provider selection and calls to LLM APIs for generating or polishing final email content.

Main functions:
- `select_provider()`: Validate and return `ollama` or `openai` from settings.
- `call_ollama(prompt)`: Send prompt to local Ollama model and return text.
- `call_openai(prompt)`: Send prompt to OpenAI chat completions and return text.

`tone_validator.py`
Validates subject/body quality and spam risk before final send.

Main functions:
- `validate_tone(email_subject, email_body)`: Run full validation and return `{passed, issues, score}`.
- `check_spam_words(text)`: Detect flagged spam words/phrases.
- `check_length(email_body)`: Enforce 50-250 word body range.
- `check_cta_present(email_body)`: Ensure a CTA keyword exists.
- `check_caps_usage(text)`: Flag too many all-caps words.
- `check_savings_claim(email_body)`: Flag unrealistic dollar claims over 50M.

`writer_agent.py`
Main Writer entry point. Coordinates contact selection, template rendering,
LLM generation, tone validation, and draft persistence.

Main functions:
- `run(company_ids, db_session)`: Process approved companies and return created draft IDs.
- `process_one_company(company_id, db_session)`: Build one full draft for one company.
- `save_draft(company_id, contact_id, subject, body, template_used, savings_estimate, db_session)`: Insert into `email_drafts`.
- `build_context(company, features, score, contact, settings)`: Build complete placeholder context.
- `format_savings_for_display(amount)`: Format compact savings values (for example, `$1.2M`, `$950k`).

## Required Settings

From `config/settings.py`:
- `LLM_PROVIDER`
- `LLM_MODEL`
- `OPENAI_API_KEY` (if using OpenAI)
- `TB_SENDER_NAME`
- `TB_SENDER_TITLE`
- `TB_PHONE`

## How It Works Together

1. `writer_agent.run()` receives approved company IDs and checks score approval.
2. `writer_agent.process_one_company()` loads company, feature, and score records.
3. The agent gets the best outreach contact from `agents.analyst.enrichment_client`.
4. `template_engine.build_context()` and `writer_agent.build_context()` prepare mergeable template values.
5. `template_engine.load_template()` loads the correct industry file from `data/templates`.
6. `template_engine.fill_static_fields()` renders the draft with static placeholders.
7. `llm_connector` generates subject/body text.
8. `tone_validator.validate_tone()` checks spam-risk and professionalism; the agent retries body generation once if needed.
9. `writer_agent.save_draft()` stores the result in `email_drafts` and updates company status to `draft_created`.

## Container

- Dockerfile: `agents/writer/Dockerfile`
- Service name in compose: `writer`
- Container command: `python agents/writer/writer_agent.py`
