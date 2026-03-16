# Database Files

This folder holds the database connection code, SQL schema files, and seed data used by the app.

`connection.py`
Creates the PostgreSQL engine, opens sessions, checks connectivity, and runs SQL migrations.

`orm_models.py`
Defines typed SQLAlchemy ORM mappings for `companies`, `company_features`, `lead_scores`,
`contacts`, `email_drafts`, and `outreach_events`. Services can import these models to use
ORM queries instead of raw SQL text statements.

Compatibility note:
- `orm_models.py` supports both SQLAlchemy 2.x and SQLAlchemy 1.4 so the main API containers and the Airflow container can import the same model definitions.

`migrations/`
Contains the SQL files that create tables in order.

Current table flow:

1. `001_create_companies.sql` creates the main `companies` table.
2. `002_create_company_features.sql` stores computed feature values for each company.
3. `003_create_lead_scores.sql` stores score results for each company.
4. `004_create_contacts.sql` stores people linked to each company.
5. `005_create_email_drafts.sql` stores outreach drafts for companies and contacts.
6. `006_create_outreach_events.sql` stores sends, replies, and follow-up activity.

`seed_data/`
Stores static JSON data such as industry benchmark values.

How it is used:

Other agents and API code open a session from `connection.py`, read or write rows in these tables, and rely on the migration files to build the database structure first.