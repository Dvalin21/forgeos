"""ForgeOS LHSR — Composite disk health scoring.

Ported from LHSR's lhsr-health.c. Combines current SMART values,
trend slopes, and error history into a single 0-100 health score.

Scoring breakdown:
  Start at 100
  Reallocated sectors:   -10 per 10 sectors (max -30)
  Pending sectors:       -15 per sector (max -30)
  Uncorrectable sectors: -20 per sector (max -40)
  Temperature > 50°C:    -10;  >60°C: -15
  Trend warnings:        -10 per active warning (realloc, pending, uncorr, temp)
  Consecutive errors:    -5 per error (max -15)
  Final clamped to 0-100

Higher = healthier. 90-100 = OK, 70-89 = WARNING,
40-69 = CRITICAL, 0-39 = FAILING.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiskHealth:
    """Current SMART health snapshot for a single disk."""
    disk_path: str
    smart_reallocated: int = 0
    smart_pending: int = 0
    smart_uncorrectable: int = 0
    temperature: int = 0
    power_on_hours: int = 0
    wear_level: int = 0
    consecutive_errors: int = 0
    # Trend warnings (from trend database)
    reallocated_warn: bool = False
    pending_warn: bool = False
    uncorrectable_warn: bool = False
    temperature_warn: bool = False


def compute_health_score(dh: DiskHealth) -> int:
    """Compute composite health score (0-100) for a disk.

    Args:
        dh: DiskHealth dataclass with current SMART values and trend warnings.

    Returns:
        Integer score from 0 (worst) to 100 (best).
    """
    score = 100

    # Reallocated sectors penalty: -10 per 10 sectors, max -30
    if dh.smart_reallocated > 0:
        p = (dh.smart_reallocated // 10) * 10
        if p > 30:
            p = 30
        score -= p

    # Pending sectors penalty: -15 per sector, max -30
    if dh.smart_pending > 0:
        p = dh.smart_pending * 15
        if p > 30:
            p = 30
        score -= p

    # Uncorrectable sectors penalty: -20 per sector, max -40
    if dh.smart_uncorrectable > 0:
        p = dh.smart_uncorrectable * 20
        if p > 40:
            p = 40
        score -= p

    # Temperature penalty
    if dh.temperature > 60:
        score -= 15
    elif dh.temperature > 50:
        score -= 10

    # Trend penalty: -10 per active warning
    if dh.reallocated_warn:
        score -= 10
    if dh.pending_warn:
        score -= 10
    if dh.uncorrectable_warn:
        score -= 10
    if dh.temperature_warn:
        score -= 10

    # Consecutive errors penalty: -5 per error, max -15
    if dh.consecutive_errors > 0:
        p = dh.consecutive_errors * 5
        if p > 15:
            p = 15
        score -= p

    # Clamp
    score = max(0, min(100, score))

    return score


def health_label(score: int) -> str:
    """Return human-readable health label for a score.

    Returns:
        One of: "OK", "WARNING", "CRITICAL", "FAILING"
    """
    if score >= 90:
        return "OK"
    if score >= 70:
        return "WARNING"
    if score >= 40:
        return "CRITICAL"
    return "FAILING"


def health_color(score: int) -> str:
    """Return CSS color class for a health score.

    Returns:
        One of: "ok", "warn", "err", "predict"
    """
    if score >= 90:
        return "ok"
    if score >= 70:
        return "warn"
    if score >= 40:
        return "err"
    return "predict"
