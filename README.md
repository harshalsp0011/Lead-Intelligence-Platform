
# Utility Lead Intelligence Platform

## 1. Project Overview

Utility Lead Intelligence Platform is an AI-assisted prospecting and outreach system for the Troy & Banks sales team. It finds target companies, scores them for fit and savings potential, generates personalized outbound emails, sends approved sequences, and monitors replies so sales can focus on the highest-intent opportunities. The platform works through five AI agents operating together in a staged pipeline: Scout discovers companies, Analyst scores and enriches them, Writer drafts outreach, Outreach manages delivery and follow-ups, and Tracker captures engagement signals and alerts the team when a prospect responds.

### Agentic Transformation Blueprint

For the detailed plan to evolve this platform from deterministic automation to a truly agentic system, see [AGENTIC_TRANSFORMATION_PLAN.md](AGENTIC_TRANSFORMATION_PLAN.md).

## 2. Architecture Overview

![Architecture Design Reference](./Design.png)

The platform is organized into six layers:

1. Data Sources
	Public directories, company websites, benchmark datasets, enrichment providers, and email/webhook providers.
2. Agent Engine
	The five operational agents plus orchestration logic that move leads through the pipeline.
3. Data Store
	PostgreSQL tables for companies, features, scores, contacts, drafts, and outreach events.
4. API Layer
	FastAPI routes that expose leads, emails, reports, pipeline health, and trigger controls.
5. Dashboard
	React frontend for operators to review leads, approve emails, launch runs, and inspect status.
6. Alerts
	Slack and email notifications for hot replies, failures, and operational visibility.

### Agent Responsibilities

| Agent | Single Responsibility |
| --- | --- |
| Scout | Finds target companies from public sources and websites. |
| Analyst | Scores leads, estimates savings, and enriches contact data. |
| Writer | Generates personalized outbound emails for approved leads. |
| Outreach | Sends emails and manages follow-up sequences. |
| Tracker | Monitors engagement, classifies replies, and alerts the sales team. |

### Layer Flow

`Data Sources -> Agent Engine -> Data Store -> API Layer -> Dashboard -> Alerts`

## 3. Prerequisites

Before starting, make sure the following are installed or created:

- Docker Desktop
- Ollama installed and running locally
- Python 3.11 or higher
- Node.js 18 or higher
- Git
- Free API keys and integrations:
  - Tavily: https://search.tavily.com
  - Hunter.io: https://hunter.io
  - SendGrid: https://sendgrid.com
  - Google Maps (Places API): https://console.cloud.google.com — enable Places API (New), free $200/month credit
  - Yelp Business Search: https://www.yelp.com/developers — create app, free 500 calls/day

Recommended local checks:

```bash
docker --version
docker compose version
python3 --version
node --version
git --version
ollama --version
```

## 4. Quick Start (Phase 1 Local)

1. Clone the repository.

	```bash
	git clone <your-repo-url>
	cd utility-lead-platform
	```

2. Copy `.env.example` to `.env`.

	```bash
	cp .env.example .env
	```

3. Fill in the free API keys in `.env`.

	Minimum keys:
	- `TAVILY_API_KEY`
	- `HUNTER_API_KEY`
	- `SENDGRID_API_KEY`
	- `SENDGRID_FROM_EMAIL`
	- `ALERT_EMAIL`
	- `GOOGLE_MAPS_API_KEY` (optional — skip to disable Google Maps source)
	- `YELP_API_KEY` (optional — skip to disable Yelp source)

4. Pull the local Ollama model.

	```bash
	ollama pull llama3.2
	```

5. Start all services.

	```bash
	docker-compose up --build
	```

6. Wait about 2 minutes for PostgreSQL, API, frontend, Airflow, Grafana, and Prometheus to initialize.

7. Run database migrations.

	```bash
	python3 -c "from database.connection import run_migrations; run_migrations()"
	```

8. Open the dashboard at `http://localhost:3000`.

9. Open Airflow at `http://localhost:8080`.
	- Username: `admin`
	- Password: `admin`

10. Open API docs at `http://localhost:8001/docs`.

11. Open Grafana at `http://localhost:3001`.

## 5. First Run Walkthrough

1. Open the dashboard at `http://localhost:3000`.
2. Click `Triggers` in the left navigation.
3. Select `Industry: Healthcare`.
4. Set `Location: Buffalo, NY`.
5. Set `Count: 10`.
6. Click `Run Full Pipeline`.
7. Watch Airflow at `http://localhost:8080` for the DAG run.
8. After 10 to 15 minutes, check the `Leads` page.
9. Review scored leads and approve the high-score ones.
10. Go to the `Email Review` page.
11. Review the generated emails.
12. Edit the subject line if needed.
13. Click `Approve` to queue the email for sending.
14. Check the SendGrid dashboard to confirm delivery.
15. Watch for a Slack alert when a prospect replies.

## 6. Configuration Reference

The project reads configuration from `.env`. Use the Phase 1 column for local and free-tier usage, then switch to Phase 2 values when you move to paid providers or cloud infrastructure.

| Variable | Description | Phase 1 Value (Free) | Phase 2 Value (Paid/Scale) | Required |
| --- | --- | --- | --- | --- |
| `DEPLOY_ENV` | Environment mode used by API auth and runtime behavior. | `local` | `production` | Required |
| `APP_NAME` | Application name for logs and service identity. | `utility-lead-platform` | `utility-lead-platform` | Required |
| `LOG_LEVEL` | Global logging verbosity. | `INFO` | `INFO` or `WARNING` | Optional |
| `TB_BRAND_NAME` | Brand label used in outbound footer content. | `Troy & Banks` | `Troy & Banks` | Required |
| `TB_OFFICE_LOCATION` | Office location shown in outbound footer content. | `Buffalo, NY` | production office location | Required |
| `UNSUBSCRIBE_INSTRUCTION` | Standard unsubscribe instruction appended to outbound emails. | `To unsubscribe reply with STOP.` | compliance-approved production text | Required |
| `LLM_PROVIDER` | Active LLM backend. | `ollama` | `openai` | Required |
| `LLM_MODEL` | Model name used by the selected LLM provider. | `llama3.2` | `gpt-4o-mini` | Required |
| `OLLAMA_BASE_URL` | Base URL for the local Ollama server. | `http://localhost:11434` | leave set only if Ollama retained | Optional |
| `OPENAI_API_KEY` | OpenAI API credential for paid hosted inference. | blank | your OpenAI key | Optional in Phase 1, required in Phase 2 if using OpenAI |
| `SEARCH_PROVIDER` | Search provider used for discovery workflows. | `tavily` | `serper` | Required |
| `TAVILY_API_KEY` | Tavily API key for free-tier search. | your Tavily free-tier key | blank or fallback only | Optional in Phase 2 |
| `SERPER_API_KEY` | Serper API key for paid search. | blank | your Serper paid key | Optional in Phase 1, required in Phase 2 if using Serper |
| `PROXY_PROVIDER` | Proxy/scraping provider selector. | `scraperapi` | `brightdata` | Required |
| `SCRAPERAPI_KEY` | ScraperAPI key for lower-volume crawling. | free or trial key | blank or backup only | Optional in Phase 2 |
| `BRIGHTDATA_KEY` | Bright Data key for scaled crawling. | blank | your Bright Data key | Optional in Phase 1, required in Phase 2 if using Bright Data |
| `REQUEST_DELAY_SECONDS` | Delay between requests to reduce blocking risk. | `2` | `1` to `2` depending on provider policy | Optional |
| `MAX_RETRIES` | Retry count for scraping/network operations. | `3` | `3` to `5` | Optional |
| `SCRAPER_REQUEST_TIMEOUT_SECONDS` | Timeout for outbound directory fetch requests. | `30` | `30` to `60` | Optional |
| `SCRAPER_USER_AGENT` | User-Agent header used for directory scraping. | browser-like default | managed production header | Optional |
| `ENRICHMENT_PROVIDER` | Contact enrichment provider selector. | `hunter` | `apollo` | Required |
| `HUNTER_API_KEY` | Hunter.io API key for free-tier enrichment. | your Hunter key | blank or backup only | Optional in Phase 2 |
| `APOLLO_API_KEY` | Apollo API key for scaled enrichment. | blank | your Apollo key | Optional in Phase 1, required in Phase 2 if using Apollo |
| `DATABASE_URL` | SQLAlchemy/PostgreSQL connection string. | `postgresql://admin:password@localhost:5432/leads` | your AWS RDS PostgreSQL URL | Required |
| `EMAIL_PROVIDER` | Email delivery provider. | `sendgrid` | `instantly` | Required |
| `SENDGRID_API_KEY` | SendGrid API key for delivery. | your SendGrid free-tier key | backup or transactional-only key | Optional in Phase 2 |
| `SENDGRID_FROM_EMAIL` | Verified sender used for outbound messages. | verified Phase 1 sender | verified production sender/domain | Required when using SendGrid |
| `INSTANTLY_API_KEY` | Instantly.ai key for scaled outreach sending. | blank | your Instantly key | Optional in Phase 1, required in Phase 2 if using Instantly |
| `INSTANTLY_CAMPAIGN_ID` | Instantly campaign identifier used for API-based lead injection. | blank | active Instantly campaign id | Optional in Phase 1, required in Phase 2 if using Instantly |
| `INSTANTLY_API_BASE_URL` | Instantly API base URL. | `https://api.instantly.ai` | provider base URL | Optional |
| `INSTANTLY_REQUEST_TIMEOUT_SECONDS` | Timeout for Instantly API calls. | `30` | `30` to `60` | Optional |
| `EMAIL_DAILY_LIMIT` | Daily cap on total sends. | `50` | `500+` based on warmup policy | Required |
| `FOLLOWUP_DAY_1` | Delay before first follow-up. | `3` | `3` | Optional |
| `FOLLOWUP_DAY_2` | Delay before second follow-up. | `7` | `7` | Optional |
| `FOLLOWUP_DAY_3` | Delay before third follow-up. | `14` | `14` | Optional |
| `API_KEY` | Header-based API key for protected routes outside local mode. | blank in local | strong secret value | Optional in Phase 1, required in Phase 2 |
| `SCOUT_TARGET_INDUSTRIES` | Weekly Airflow scout target industries. | `all` | comma-separated production targets | Optional |
| `SCOUT_TARGET_LOCATIONS` | Weekly Airflow scout target locations. | `all` | comma-separated production targets | Optional |
| `SCOUT_WEEKLY_TARGET_COUNT` | Weekly target count for scheduled scout runs. | `20` | production weekly target | Optional |
| `ALERT_EMAIL` | Email address for all reply and ops alerts. No Slack used. | sales team email | monitored ops/sales inbox | Required |
| `GOOGLE_MAPS_API_KEY` | Google Places API key for company discovery. Requires billing account but $200/month free credit — free at this scale. | your key or blank to disable | your key | Optional |
| `YELP_API_KEY` | Yelp Business Search API key. Fully free, 500 calls/day. | your key or blank to disable | your key | Optional |
| `SCORE_WEIGHT_RECOVERY` | Weight for savings recovery in scoring. | `0.40` | `0.40` | Optional |
| `SCORE_WEIGHT_INDUSTRY` | Weight for industry fit in scoring. | `0.25` | `0.25` | Optional |
| `SCORE_WEIGHT_MULTISITE` | Weight for site-count signal in scoring. | `0.20` | `0.20` | Optional |
| `SCORE_WEIGHT_DATA_QUALITY` | Weight for completeness/quality signal in scoring. | `0.15` | `0.15` | Optional |
| `HIGH_SCORE_THRESHOLD` | Score threshold for high-priority leads. | `70` | `70` or tuned from live data | Optional |
| `MEDIUM_SCORE_THRESHOLD` | Score threshold for medium-priority leads. | `40` | `40` or tuned from live data | Optional |
| `TB_CONTINGENCY_FEE` | Troy & Banks fee ratio for revenue projection. | `0.24` | `0.24` or current commercial rate | Required |
| `TB_SENDER_NAME` | Name inserted into generated outbound emails. | assigned sender name | production sender name | Required for email generation |
| `TB_SENDER_TITLE` | Title inserted into generated outbound emails. | assigned sender title | production sender title | Required for email generation |
| `TB_PHONE` | Callback phone number included in email context. | Troy & Banks line | production line | Required for email generation |

## 7. Phase 1 to Phase 2 Upgrade

The platform is designed so the Phase 1 to Phase 2 transition is primarily a configuration change, not a code rewrite.

### What Changes

| Capability | Phase 1 | Phase 2 |
| --- | --- | --- |
| LLM | Ollama | OpenAI GPT-4o mini |
| Database | Local PostgreSQL | AWS RDS PostgreSQL |
| Search | Tavily free tier | Serper paid |
| Proxies | ScraperAPI free/trial | Bright Data |
| Contacts | Hunter.io free tier | Apollo.io paid |
| Email | SendGrid free tier | Instantly.ai |

### How to Upgrade

1. Open `.env`.
2. Change provider selectors such as `LLM_PROVIDER`, `SEARCH_PROVIDER`, `PROXY_PROVIDER`, `ENRICHMENT_PROVIDER`, and `EMAIL_PROVIDER`.
3. Replace local/free-tier credentials with paid production credentials.
4. Update `DATABASE_URL` to point at AWS RDS.
5. Restart the stack.

```bash
docker-compose down
docker-compose up --build -d
```

No code changes are required if your provider values and credentials are set correctly.

## 8. Deployment to AWS

1. Launch a `t3.medium` EC2 instance running Ubuntu 22.04.
2. SSH into the instance.

	```bash
	ssh -i /path/to/key.pem ubuntu@<ec2-public-ip>
	```

3. Install Docker and Docker Compose on EC2.

	```bash
	sudo apt update
	sudo apt install -y docker.io docker-compose-plugin git
	sudo systemctl enable --now docker
	sudo usermod -aG docker $USER
	```

4. Clone the repository to EC2.

	```bash
	git clone <your-repo-url>
	cd utility-lead-platform
	```

5. Copy your `.env` file to EC2 and replace Phase 1 values with Phase 2 credentials.

6. Run the platform in detached mode.

	```bash
	docker-compose up --build -d
	```

7. Configure the EC2 security group to open ports `80`, `443`, `3000`, and `8001`.
8. Point your domain DNS `A` record to the EC2 public IP.
9. Install an SSL certificate with Let's Encrypt.
10. Access the dashboard using your domain.

Typical production hardening after first deploy:

- Put Nginx or another reverse proxy in front of the frontend and API.
- Restrict direct access to internal-only ports where possible.
- Move PostgreSQL to AWS RDS instead of exposing the containerized local database externally.
- Store `.env` securely and rotate external credentials.

## 9. Agent Reference

### Scout

- Purpose: Finds target companies from directories and company websites.
- Input: Industry, location, target count, directory source list.
- Output: Normalized company records plus website-derived enrichment signals stored in the database.
- Key scripts: `agents/scout/scout_agent.py`, `agents/scout/directory_scraper.py`, `agents/scout/company_extractor.py`, `agents/scout/website_crawler.py`.
- Manual test run:

  ```bash
  python3 -c "from database.connection import get_db; from agents.scout import scout_agent; db = get_db(); print(scout_agent.run('healthcare', 'Buffalo, NY', 5, db))"
  ```

### Analyst

- Purpose: Scores discovered companies and estimates spend, savings, and revenue opportunity.
- Input: Company IDs or discovered company rows, benchmark seed data, enrichment provider credentials.
- Output: `company_features`, `lead_scores`, and optionally enriched contacts.
- Key scripts: `agents/analyst/analyst_agent.py`, `agents/analyst/benchmarks_loader.py`, `agents/analyst/spend_calculator.py`, `agents/analyst/savings_calculator.py`, `agents/analyst/score_engine.py`, `agents/analyst/enrichment_client.py`.
- Manual test run:

  ```bash
  python3 -c "from database.connection import get_db; from agents.analyst import analyst_agent; db = get_db(); print(analyst_agent.run(['<company-id>'], db))"
  ```

### Writer

- Purpose: Generates personalized email drafts for approved, scored leads.
- Input: Company, feature, score, contact, and sender context.
- Output: Email drafts stored in `email_drafts`.
- Key scripts: `agents/writer/writer_agent.py`, `agents/writer/template_engine.py`, `agents/writer/llm_connector.py`, `agents/writer/tone_validator.py`.
- Manual test run:

  ```bash
  python3 -c "from database.connection import get_db; from agents.writer import writer_agent; db = get_db(); print(writer_agent.process_one_company('<company-id>', db))"
  ```

### Outreach

- Purpose: Sends approved emails and manages the follow-up queue.
- Input: Approved drafts, contact records, provider credentials, daily send limits.
- Output: Sent email activity in `outreach_events` and scheduled follow-up records.
- Key scripts: `agents/outreach/outreach_agent.py`, `agents/outreach/email_sender.py`, `agents/outreach/followup_scheduler.py`, `agents/outreach/sequence_manager.py`.
- Manual test run:

  ```bash
  python3 -c "from database.connection import get_db; from agents.outreach import outreach_agent; db = get_db(); print(outreach_agent.process_followup_queue(db))"
  ```

### Tracker

- Purpose: Watches engagement events, classifies replies, updates lead state, and alerts sales.
- Input: SendGrid webhook events, reply text, outreach event history, Slack/email alert settings.
- Output: Updated lifecycle states, logged engagement events, and real-time alerts for hot replies.
- Key scripts: `agents/tracker/tracker_agent.py`, `agents/tracker/webhook_listener.py`, `agents/tracker/reply_classifier.py`, `agents/tracker/status_updater.py`, `agents/tracker/alert_sender.py`.
- Manual test run:

  ```bash
  python3 -c "from database.connection import get_db; from agents.tracker import tracker_agent; db = get_db(); print(tracker_agent.run_daily_checks(db))"
  ```

## 10. Troubleshooting

### Ollama not responding

Fix:

```bash
ollama serve
```

Also verify:

```bash
curl http://localhost:11434/api/tags
```

### PostgreSQL connection refused

Fix: make sure Docker Compose is running and the PostgreSQL container is healthy.

```bash
docker ps
docker-compose up -d postgres
```

### Tavily returning no results

Fix:

- Check `TAVILY_API_KEY` in `.env`.
- Confirm the free-tier limit has not been exceeded.
- Restart the affected service after changing credentials.

### SendGrid emails not delivering

Fix:

- Verify the sender email in SendGrid.
- Confirm `SENDGRID_FROM_EMAIL` matches the verified sender identity.
- Check the SendGrid activity feed for rejected or blocked messages.

### Airflow DAG not appearing

Fix:

```bash
docker-compose restart airflow
docker logs <airflow-container-name>
```

Also verify that the `dags/` folder contains the expected DAG files. This project mounts the DAG and project folders directly into the Airflow container.

### Dashboard blank page

Fix:

- Confirm the frontend container is running.
- Confirm the API container is running.
- Check that the dashboard is pointing to the correct API host.

```bash
docker ps
```

If you use a custom frontend environment, verify `REACT_APP_API_URL` points to the correct host.

### Agents producing no leads

Fix:

- Check `directory_sources` table for active sources.
- Run Scout manually from the Triggers page or via a direct Python command.
- Check Airflow and container logs for errors from Scout or Analyst.

Useful commands:

```bash
docker logs <scout-container-name>
docker logs <api-container-name>
docker logs <airflow-container-name>
```