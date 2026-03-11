from __future__ import annotations

"""Benchmark data loader for Analyst workflows.

This module reads industry benchmark seed data once, keeps it in memory, and
serves helper lookups for industry and electricity-rate values.
"""

import json
from pathlib import Path
from typing import Any, Optional

_BENCHMARKS_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "seed_data"
    / "industry_benchmarks.json"
)

_BENCHMARKS_CACHE: Optional[dict[str, Any]] = None


def load_benchmarks() -> dict[str, Any]:
    """Load benchmark JSON once and return the cached data on future calls."""
    global _BENCHMARKS_CACHE

    if _BENCHMARKS_CACHE is None:
        _BENCHMARKS_CACHE = json.loads(_BENCHMARKS_PATH.read_text(encoding="utf-8"))

    assert _BENCHMARKS_CACHE is not None
    return _BENCHMARKS_CACHE


def get_benchmark(industry: str, state: str) -> dict[str, float]:
    """Return benchmark metrics for an industry bucket and state code."""
    benchmarks = load_benchmarks()
    industry_rows = benchmarks.get("industry_benchmarks", [])

    industry_key = (industry or "").strip().lower()
    matched_row = next(
        (
            row
            for row in industry_rows
            if str(row.get("industry_bucket", "")).strip().lower() == industry_key
        ),
        None,
    )

    if matched_row is None:
        raise ValueError(f"No benchmark found for industry '{industry}'")

    return {
        "avg_sqft_per_site": float(matched_row.get("avg_sqft_per_site", 0.0)),
        "kwh_per_sqft_per_year": float(matched_row.get("kwh_per_sqft_per_year", 0.0)),
        "telecom_per_employee": float(matched_row.get("telecom_per_employee", 0.0)),
        "electricity_rate": get_electricity_rate(state),
    }


def get_electricity_rate(state: str) -> float:
    """Return the electricity rate for a state code or default fallback."""
    benchmarks = load_benchmarks()
    state_rates = benchmarks.get("electricity_rate_by_state", {})

    normalized_state = (state or "").strip().upper()
    return float(state_rates.get(normalized_state, state_rates.get("default", 0.12)))


def refresh_benchmarks() -> None:
    """Clear in-memory benchmark cache so data reloads on next access."""
    global _BENCHMARKS_CACHE
    _BENCHMARKS_CACHE = None
