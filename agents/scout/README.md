# Scout Agent Files

This folder holds the code that finds company data from public directories.

`scout_agent.py`
Main coordinator for the Scout workflow. It chooses sources, runs scraping,
validates candidates, enriches data from company websites, and saves records.

`directory_scraper.py`
Loads active sources, downloads directory pages, follows pagination, and returns raw company listing cards.

`company_extractor.py`
Takes those raw listing cards, cleans the fields, normalizes values like state and phone, checks duplicates, and saves companies to the database.

`website_crawler.py`
Visits each company website (including JavaScript-rendered pages via Playwright) and extracts enrichment signals such as location count, employee signals, and facility type.

How they work together:

1. `scout_agent.py` starts the run with target industry, location, and count.
2. It loads sources from `data/sources/directory_urls.json`.
3. It calls `directory_scraper.py` to fetch listing pages.
4. It sends each listing into `company_extractor.py` for cleanup and normalization.
5. It uses `website_crawler.py` for website-based enrichment signals.
6. It saves cleaned and enriched records into the database tables.

This means the scraper collects raw directory data, the extractor normalizes it,
and the crawler adds website intelligence before persistence.

## Container

- Dockerfile: `agents/scout/Dockerfile`
- Service name in compose: `scout`
- Container command: `python agents/scout/scout_agent.py`