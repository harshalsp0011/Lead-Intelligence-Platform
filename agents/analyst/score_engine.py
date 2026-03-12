from __future__ import annotations

"""Scoring and tiering helpers for Analyst workflows.

This module converts company signals into score components, assigns lead tiers,
and generates human-readable score explanations.
"""

from config.settings import get_settings


def score_multisite(site_count: int) -> float:
    """Return multisite score component (0 to 20 points)."""
    if site_count >= 20:
        return 20.0
    if site_count >= 10:
        return 17.0
    if site_count >= 5:
        return 13.0
    if site_count >= 2:
        return 8.0
    return 3.0


def score_data_quality(data_quality_score: float) -> float:
    """Return data quality score component (0 to 15 points)."""
    if data_quality_score >= 9:
        return 15.0
    if data_quality_score >= 7:
        return 12.0
    if data_quality_score >= 5:
        return 8.0
    if data_quality_score >= 3:
        return 4.0
    return 1.0


def compute_score(
    savings_mid: float,
    industry: str,
    site_count: int,
    data_quality_score: float,
) -> float:
    """Return total weighted score on a 0-100 scale."""
    settings = get_settings()

    recovery_score = _score_recovery(savings_mid)
    industry_score = _score_industry(industry)
    multisite_score = score_multisite(site_count)
    quality_score = score_data_quality(data_quality_score)

    total = (
        recovery_score * float(settings.SCORE_WEIGHT_RECOVERY)
        + industry_score * float(settings.SCORE_WEIGHT_INDUSTRY)
        + multisite_score * float(settings.SCORE_WEIGHT_MULTISITE)
        + quality_score * float(settings.SCORE_WEIGHT_DATA_QUALITY)
    )
    return round(total, 2)


def assign_tier(score: float) -> str:
    """Assign high/medium/low tier using configured thresholds."""
    settings = get_settings()
    high_threshold = settings.HIGH_SCORE_THRESHOLD
    medium_threshold = settings.MEDIUM_SCORE_THRESHOLD

    if score >= float(high_threshold):
        return "high"
    if score >= float(medium_threshold):
        return "medium"
    return "low"


def generate_score_reason(
    industry: str,
    site_count: int,
    savings_mid: float,
    data_quality_score: float,
    deregulated_state: bool,
) -> str:
    """Generate a plain-language explanation of score-driving factors."""
    industry_text = (industry or "unknown").replace("_", " ")

    sentences = [f"{site_count}-site {industry_text} organization identified."]

    if deregulated_state:
        sentences.append("Operating in a deregulated energy market.")

    sentences.append(
        f"Estimated ${savings_mid / 1_000_000:.1f}M in recoverable savings."
        if savings_mid >= 1_000_000
        else f"Estimated ${savings_mid / 1_000:.0f}k in recoverable savings."
    )

    if industry_text in {"healthcare", "hospitality", "manufacturing", "retail"}:
        sentences.append("High energy intensity industry with strong audit fit.")
    else:
        sentences.append("Industry profile shows moderate audit fit.")

    if data_quality_score < 5:
        sentences.append("Data quality is currently limited and may require manual verification.")

    return " ".join(sentences)


def assess_data_quality(
    site_count: int,
    employee_count: int,
    has_website: bool,
    has_locations_page: bool,
    has_contact_found: bool,
) -> float:
    """Return quality score from 0 to 10 based on available company signals."""
    score = 0.0
    if has_website:
        score += 2
    if has_locations_page:
        score += 2
    if site_count > 0:
        score += 2
    if employee_count > 0:
        score += 2
    if has_contact_found:
        score += 2
    return score


def _score_recovery(savings_mid: float) -> float:
    if savings_mid >= 2_000_000:
        return 100.0
    if savings_mid >= 1_000_000:
        return 85.0
    if savings_mid >= 500_000:
        return 70.0
    if savings_mid >= 250_000:
        return 55.0
    return 40.0


def _score_industry(industry: str) -> float:
    normalized = (industry or "").strip().lower()
    if normalized in {"healthcare", "hospitality", "manufacturing", "retail"}:
        return 90.0
    if normalized in {"public_sector", "office"}:
        return 70.0
    if normalized == "unknown":
        return 45.0
    return 55.0


class ScoreEngine:
    """Class-based interface for scoring calculations (used by test suite)."""

    # Component score limits
    RECOVERY_SCORE_MAX = 40
    INDUSTRY_SCORE_MAX = 25
    MULTISITE_SCORE_MAX = 20
    DATA_QUALITY_SCORE_MAX = 15

    # Industry-specific point values
    INDUSTRY_SCORES = {
        'healthcare': 25,
        'hospitality': 20,
        'manufacturing': 22,
        'public_sector': 18,
        'retail': 15,
        'unknown': 0,
    }

    # Recovery score thresholds
    RECOVERY_THRESHOLDS = [
        (2_000_000, 40),
        (1_000_000, 30),
        (500_000, 25),
        (300_000, 20),
        (0, 0),
    ]

    def score_recovery(self, savings_mid: float) -> float:
        """
        Calculate recovery/savings score component (0-40 points).

        Score increases with higher savings amounts:
        - >= $2M: 40 points
        - >= $1M: 30 points
        - >= $500k: 25 points
        - >= $300k: 20 points
        - < $300k: 0 points
        """
        for threshold, points in self.RECOVERY_THRESHOLDS:
            if savings_mid >= threshold:
                return float(points)
        return 0.0

    def score_industry(self, industry: str) -> float:
        """
        Calculate industry score component (0-25 points).

        Industry-specific scores reflect audit potential:
        - healthcare: 25 points
        - manufacturing: 22 points
        - hospitality: 20 points
        - public_sector: 18 points
        - retail: 15 points
        - unknown: 0 points
        """
        normalized = (industry or "").strip().lower()
        return float(self.INDUSTRY_SCORES.get(normalized, 0))

    def assign_tier(self, score: float) -> str:
        """
        Assign lead tier based on composite score.

        Tiers:
        - high: score >= 70
        - medium: score >= 50
        - low: score < 50
        """
        if score >= 70:
            return 'high'
        if score >= 50:
            return 'medium'
        return 'low'

    def compute_score(
        self,
        savings_mid: float,
        industry: str,
        site_count: int,
        data_quality_score: float,
        deregulated_state: bool = False,
    ) -> float:
        """
        Calculate composite lead score (0-100).

        Components:
        - Recovery: 0-40 points (savings amount)
        - Industry: 0-25 points (industry type)
        - Multisite: 0-20 points (site count)
        - Data quality: 0-15 points (data quality)

        Args:
            savings_mid (float): Mid-tier savings estimate in dollars
            industry (str): Industry category
            site_count (int): Number of facilities
            data_quality_score (float): Data quality score 0-10
            deregulated_state (bool): Whether operating in deregulated market (bonus consideration)

        Returns:
            float: Composite score 0-100
        """
        recovery = self.score_recovery(savings_mid)
        industry_score = self.score_industry(industry)
        multisite = self._score_multisite(site_count)
        quality = self._score_data_quality(data_quality_score)

        total = recovery + industry_score + multisite + quality

        # Deregulated state is a positive factor but doesn't add fixed points
        # (already reflected through other components)

        return round(min(total, 100.0), 2)

    def _score_multisite(self, site_count: int) -> float:
        """Calculate multisite score component (0-20 points)."""
        if site_count >= 20:
            return 20.0
        if site_count >= 10:
            return 17.0
        if site_count >= 5:
            return 13.0
        if site_count >= 2:
            return 8.0
        return 3.0

    def _score_data_quality(self, data_quality_score: float) -> float:
        """Calculate data quality score component (0-15 points)."""
        if data_quality_score >= 9:
            return 15.0
        if data_quality_score >= 7:
            return 12.0
        if data_quality_score >= 5:
            return 8.0
        if data_quality_score >= 3:
            return 4.0
        return 1.0
