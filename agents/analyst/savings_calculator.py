from __future__ import annotations

"""Savings and revenue estimation helpers for Analyst workflows."""

from config.settings import get_settings


def calculate_savings_low(total_spend: float) -> float:
    """Return low savings estimate (10% of total spend)."""
    return float(total_spend) * 0.10


def calculate_savings_mid(total_spend: float) -> float:
    """Return mid savings estimate (13.5% of total spend)."""
    return float(total_spend) * 0.135


def calculate_savings_high(total_spend: float) -> float:
    """Return high savings estimate (17% of total spend)."""
    return float(total_spend) * 0.17


def calculate_all_savings(total_spend: float) -> dict[str, float]:
    """Return all savings estimates as one dictionary."""
    return {
        "low": calculate_savings_low(total_spend),
        "mid": calculate_savings_mid(total_spend),
        "high": calculate_savings_high(total_spend),
    }


def calculate_tb_revenue(savings_mid: float) -> float:
    """Return expected Troy & Banks revenue from mid savings estimate."""
    settings = get_settings()
    contingency_fee = getattr(settings, "TB_CONTINGENCY_FEE", 0.24)
    return float(savings_mid) * float(contingency_fee)


def format_savings_for_display(savings_low: float, savings_high: float) -> str:
    """Return human-friendly savings range string (for example, '$1.2M – $2.1M')."""
    return f"{_format_currency_short(savings_low)} – {_format_currency_short(savings_high)}"


def _format_currency_short(value: float) -> str:
    amount = float(value)

    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.1f}k"
    return f"${amount:,.0f}"
