# Writer Agent

Generates personalised outreach email drafts for approved high-tier companies.
No email is sent until a human reviews and approves each draft on the Email Review page.

---

## How It Works

```
writer_agent.run(company_ids, db_session, run_id)
  ↓
For each approved company (LeadScore.approved_human=True, tier=high, no existing draft):
  1. Load company, features, score, contact from DB
  2. Query email_win_rate → get best-performing angle for this industry (if ≥5 data points)
  3. Build writer context (company profile + contact + analyst note + angle hint)
  4. Writer LLM reasons about best angle → generates full email (subject + body + ANGLE name)
  5. Critic evaluates draft 0–10 on 5 criteria
  6. If score < 7: Writer rewrites using Critic feedback (max 2 rewrites)
  7. If still < 7 after 2 rewrites: save with low_confidence=true
  8. Save draft to email_drafts with template_used = chosen angle name
  9. Update AgentRun.drafts_created counter (live progress)
  10. Set company.status = "draft_created"
```

---

## Agentic Concepts Used

| Concept | Where | What it does |
|---|---|---|
| **Context-Aware Generation** | `_WRITER_PROMPT` | LLM reads score_reason + company signals, reasons about angle before writing |
| **Self-Critique / Reflection** | `critic_agent.evaluate()` | Critic scores the draft, Writer rewrites on specific feedback |
| **Learning from Feedback** | `get_best_angle()` | Reads `email_win_rate` to bias angle selection toward what worked in this industry |
| **Uncertainty Flagging** | `low_confidence=True` | Saved when draft never reaches 7/10 — flagged in Email Review UI |
| **Graceful Degradation** | no-contact fallback | If no contact found, writes generic draft to "[Company] team" — doesn't skip |
| **Observable Execution** | `AgentRun` row | `drafts_created` incremented per draft so Triggers page shows live count |

---

## Angles

The Writer picks one angle per email from a fixed set. The chosen angle is saved as `template_used`
in `email_drafts` so the Tracker can update `email_win_rate` when a reply comes in.

| Angle | Lead with |
|---|---|
| `cost_savings` | Dollar savings estimate up front |
| `audit_offer` | Free no-commitment energy audit |
| `risk_reduction` | Utility cost volatility / budget risk |
| `multi_site_savings` | Multi-location efficiency opportunity |
| `deregulation_opportunity` | Open energy market / supplier switch |

---

## Win Rate Learning

`get_best_angle(industry, db_session)` queries `email_win_rate` for the highest `reply_rate`
for this industry. Requires ≥5 emails sent before the data is trusted (cold-start protection).

```sql
SELECT template_id, reply_rate
FROM email_win_rate
WHERE industry = :industry
  AND emails_sent >= 5
ORDER BY reply_rate DESC
LIMIT 1
```

- **Cold start (no data):** `angle_hint = ""` — LLM picks freely based on company context
- **With history:** `WIN RATE HINT` injected into prompt — LLM told which angle has highest reply rate and reasons whether to follow or override it

After each reply event, the Tracker updates `email_win_rate.reply_rate` for the `(template_id, industry)` pair.
After enough data accumulates, the Writer automatically biases toward the winning angle.

---

## Critic Rubric

Critic evaluates on 5 criteria × 2 points each (max 10):

| Criterion | What it checks |
|---|---|
| Personalised | Mentions company name and something specific to them |
| Specific number | Has a dollar figure (e.g. "$180k") not just "significant savings" |
| Clear CTA | One specific ask — call, meeting, reply |
| Sounds human | Not template-like, reads naturally |
| Subject line | Specific and relevant, not generic |

Score ≥ 7 → saved. Score < 7 → rewrite. Still < 7 after 2 rewrites → `low_confidence=true`.

---

## Run Tracking

When `orchestrator.run_writer()` fires:
1. Creates `AgentRun` row: `status="writer_running"`, `current_stage="writer_running"`
2. `run_id` passed through `task_manager` → `writer_agent.run(run_id=...)`
3. After each draft: `agent_runs.drafts_created` incremented (visible via `/pipeline/run/{run_id}`)
4. On completion: `status="writer_awaiting_approval"`, `current_stage="writer_complete"`
5. Notification email sent to `ALERT_EMAIL` with draft table + link to Email Review page

---

## Notification Email

After Writer finishes, `email_notifier.send_draft_approval_request()` sends to `ALERT_EMAIL`:
- Table of all drafts: Company | Contact | Subject Line | Angle | AI Score
- Yellow warning banner if any drafts have `low_confidence=true`
- "No emails have been sent yet" — stated explicitly
- "Review & Approve Drafts →" button linking to Email Review page (`/emails`)
- A `HumanApprovalRequest` row is created (`approval_type="emails"`) to track the pending review

---

## Rejection Flow

When a draft is rejected on the Email Review page:
- Draft deleted from `email_drafts`
- `company.status` reset from `"draft_created"` → `"approved"`
- Company re-appears in the "✉️ Generate Drafts" count on the Triggers page
- No email sent
- Human can re-run Writer (picks up the company since no draft exists) or click Regenerate directly

---

## Files

| File | Purpose |
|---|---|
| `writer_agent.py` | Main entry point — win rate query, context build, Writer→Critic loop, persistence |
| `critic_agent.py` | Critic LLM — evaluates draft 0–10, returns score + feedback |
| `llm_connector.py` | LLM API calls — Ollama (default) or OpenAI |
| `template_engine.py` | Legacy template loader — kept for backward compatibility |
| `tone_validator.py` | Rule-based spam/length/CTA check — legacy, not used in main flow |

---

## Data Contract

**Input:** companies where `lead_scores.approved_human=True`, `tier="high"`, no row in `email_drafts`

**Output per company:**

| Field | Value |
|---|---|
| `email_drafts.subject_line` | Specific to this company (name or detail) |
| `email_drafts.body` | 100–160 words, savings figure, clear CTA |
| `email_drafts.template_used` | Angle name chosen by LLM (e.g. `cost_savings`) |
| `email_drafts.critic_score` | Final Critic score (0–10) |
| `email_drafts.low_confidence` | `true` if draft never reached 7/10 |
| `email_drafts.rewrite_count` | 0, 1, or 2 |
| `company.status` | Updated to `"draft_created"` |

---

## LLM Usage

- **Provider:** Ollama llama3.2 (local, free) or OpenAI gpt-4o-mini (set `LLM_PROVIDER=openai`)
- **Calls per email:** 2–6 (1 write + 1–2 Critic evaluations + 0–2 rewrites)
- **Cost with Ollama:** $0
- **Cost with gpt-4o-mini:** ~$0.0015 per email
