from __future__ import annotations

"""Spend estimation helpers for Analyst workflows.

This module converts benchmark values into annual utility and telecom spend
estimates used by scoring and opportunity sizing logic.
"""

from agents.analyst.benchmarks_loader import get_benchmark
from agents.analyst.benchmarks_loader import get_electricity_rate as get_state_electricity_rate


def calculate_utility_spend(site_count: int, industry: str, state: str) -> float:
    """Estimate annual utility spend in USD for a multi-site company."""
    benchmark = get_benchmark(industry, state)
    spend = (
        float(site_count)
        * benchmark["avg_sqft_per_site"]
        * benchmark["kwh_per_sqft_per_year"]
        * benchmark["electricity_rate"]
    )
    return spend


def calculate_telecom_spend(employee_count: int, industry: str) -> float:
    """Estimate annual telecom spend in USD from employee count."""
    benchmark = get_benchmark(industry, "")
    spend = float(employee_count) * benchmark["telecom_per_employee"]
    return spend


def calculate_total_spend(utility_spend: float, telecom_spend: float) -> float:
    """Return combined annual utility + telecom spend."""
    return float(utility_spend) + float(telecom_spend)


def get_avg_sqft_per_site(industry: str) -> float:
    """Return benchmark average square footage per site for an industry."""
    benchmark = get_benchmark(industry, "")
    return benchmark["avg_sqft_per_site"]


def get_kwh_per_sqft(industry: str) -> float:
    """Return benchmark kWh per sqft per year for an industry."""
    benchmark = get_benchmark(industry, "")
    return benchmark["kwh_per_sqft_per_year"]


def get_electricity_rate(state: str) -> float:
    """Return electricity rate ($/kWh) for a state code."""
    return get_state_electricity_rate(state)
