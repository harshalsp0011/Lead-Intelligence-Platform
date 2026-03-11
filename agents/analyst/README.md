# Analyst Agent Files

This folder holds helper code used by the Analyst workflow to calculate company-level estimates and scoring inputs.

`benchmarks_loader.py`
Loads benchmark data from `database/seed_data/industry_benchmarks.json`, caches it in memory, and provides lookup helpers.

`spend_calculator.py`
Uses benchmark values to estimate annual utility spend, telecom spend, and total spend.
It also exposes helper lookups for `avg_sqft_per_site`, `kwh_per_sqft_per_year`, and electricity rate.

`savings_calculator.py`
Converts total spend into low/mid/high savings ranges, calculates expected Troy & Banks revenue,
and formats savings for display in reports.

`score_engine.py`
Calculates score components (multisite and data quality), assigns lead tier,
builds a human-readable score reason, and computes a 0-10 data quality signal.

`analyst_agent.py`
Main Analyst entry point. Processes one company at a time, coordinates spend,
savings, quality, scoring, and writes results into `company_features` and `lead_scores`.

Main functions:

1. `load_benchmarks()`
Reads and caches the full benchmark JSON so repeated lookups are fast.

2. `get_benchmark(industry, state)`
Returns combined values for one industry bucket and one state:
`avg_sqft_per_site`, `kwh_per_sqft_per_year`, `telecom_per_employee`, and `electricity_rate`.

3. `get_electricity_rate(state)`
Returns state electricity rate, falling back to the default value if missing.

4. `refresh_benchmarks()`
Clears in-memory cache so the next `load_benchmarks()` call reloads from disk.

How it is used:

1. Analyst code calls `spend_calculator.py` functions during feature estimation.
2. `spend_calculator.py` reads benchmark values via `benchmarks_loader.py`.
3. The returned values feed utility spend, telecom spend, and total spend calculations.
4. Analyst code calls `savings_calculator.py` to generate low/mid/high savings outputs.
5. The mid savings value can be converted into expected Troy & Banks revenue.
6. Analyst code calls `score_engine.py` to score multisite fit, data quality, and assign lead tier.
7. `score_engine.py` also generates a plain-language reason string for explainability.
8. `analyst_agent.py` stores derived features in `company_features`.
9. `analyst_agent.py` stores final score + tier in `lead_scores` and marks company status as `scored`.
10. If seed data changes, call `refresh_benchmarks()` to pick up new values without restarting the process.
