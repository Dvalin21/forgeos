"""ForgeOS LHSR — SMART trend tracking with SQLite.

Ported from LHSR's lhsr-trend.c. Stores daily SMART snapshots and computes
linear regression slopes for predictive failure analysis.

Thresholds (per day):
  Reallocated sectors:   > 1.0 / day
  Pending sectors:       > 1.0 / day
  Uncorrectable sectors: > 0.5 / day
  Temperature:           > 2.0 °C / day
"""

from __future__ import annotations

import sqlite3
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("forgeos-lhsr-trend")

# Snapshot interval (seconds) — don't record more than once per interval
SNAPSHOT_INTERVAL = 3600  # 1 hour

# Trend warning thresholds (per day)
THRESHOLD_REALLOCATED = 1.0
THRESHOLD_PENDING = 1.0
THRESHOLD_UNCORRECTABLE = 0.5
THRESHOLD_TEMPERATURE = 2.0

# Database schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS smart_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    disk_path       TEXT    NOT NULL,
    snapshot_time   INTEGER NOT NULL,
    reallocated     INTEGER DEFAULT 0,
    pending         INTEGER DEFAULT 0,
    uncorrectable   INTEGER DEFAULT 0,
    temperature     INTEGER DEFAULT 0,
    power_on_hours  INTEGER DEFAULT 0,
    wear_level      INTEGER DEFAULT 0,
    health_score    INTEGER DEFAULT 100,
    UNIQUE(disk_path, snapshot_time)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_disk_time
    ON smart_snapshots(disk_path, snapshot_time);
"""


@dataclass
class TrendResult:
    """Linear regression result for a disk."""
    data_points: int = 0
    reallocated_slope: float = 0.0
    pending_slope: float = 0.0
    uncorrectable_slope: float = 0.0
    temperature_slope: float = 0.0
    reallocated_warn: bool = False
    pending_warn: bool = False
    uncorrectable_warn: bool = False
    temperature_warn: bool = False


class TrendDB:
    """SQLite-backed SMART trend database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self) -> None:
        """Open (or create) the database."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        logger.info("Trend DB opened: %s", self.db_path)

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def record_snapshot(
        self,
        disk_path: str,
        reallocated: int = 0,
        pending: int = 0,
        uncorrectable: int = 0,
        temperature: int = 0,
        power_on_hours: int = 0,
        wear_level: int = 0,
        health_score: int = 100,
    ) -> bool:
        """Record a SMART snapshot for a disk.

        Skips if a snapshot exists within SNAPSHOT_INTERVAL seconds.
        Returns True if recorded, False if skipped.
        """
        if not self.conn:
            return False

        now = int(time.time())

        # Check if we already have a recent snapshot
        row = self.conn.execute(
            "SELECT MAX(snapshot_time) FROM smart_snapshots WHERE disk_path = ?",
            (disk_path,),
        ).fetchone()

        if row and row[0] and (now - row[0]) < SNAPSHOT_INTERVAL:
            return False

        # Insert new snapshot
        self.conn.execute(
            """INSERT OR IGNORE INTO smart_snapshots
               (disk_path, snapshot_time, reallocated, pending, uncorrectable,
                temperature, power_on_hours, wear_level, health_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (disk_path, now, reallocated, pending, uncorrectable,
             temperature, power_on_hours, wear_level, health_score),
        )
        self.conn.commit()
        logger.debug("Recorded snapshot for %s (realloc=%d pending=%d temp=%d)",
                     disk_path, reallocated, pending, temperature)
        return True

    def query_trend(self, disk_path: str) -> Optional[TrendResult]:
        """Query linear regression trend for a disk.

        Returns TrendResult with slopes and warning flags, or None if
        insufficient data (< 3 points).
        """
        if not self.conn:
            return None

        rows = self.conn.execute(
            """SELECT snapshot_time, reallocated, pending, uncorrectable, temperature
               FROM smart_snapshots
               WHERE disk_path = ?
               ORDER BY snapshot_time DESC LIMIT 30""",
            (disk_path,),
        ).fetchall()

        if len(rows) < 3:
            return None

        # Linear regression: slope = (n*sum_xy - sum_x*sum_y) / (n*sum_xx - sum_x^2)
        n = 0
        sum_x = 0.0
        sum_y_re = 0.0
        sum_y_pe = 0.0
        sum_y_un = 0.0
        sum_y_tm = 0.0
        sum_xy_re = 0.0
        sum_xy_pe = 0.0
        sum_xy_un = 0.0
        sum_xy_tm = 0.0
        sum_xx = 0.0
        base_x = 0.0

        for i, (ts, re, pe, un, tm) in enumerate(rows):
            if i == 0:
                base_x = float(ts)
            x = (float(ts) - base_x) / 86400.0  # Convert to days

            n += 1
            sum_x += x
            sum_y_re += float(re)
            sum_y_pe += float(pe)
            sum_y_un += float(un)
            sum_y_tm += float(tm)
            sum_xy_re += x * float(re)
            sum_xy_pe += x * float(pe)
            sum_xy_un += x * float(un)
            sum_xy_tm += x * float(tm)
            sum_xx += x * x

        if n < 3:
            return None

        result = TrendResult(data_points=n)

        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            return result  # All x values identical

        # Compute slopes
        result.reallocated_slope = (n * sum_xy_re - sum_x * sum_y_re) / denom
        result.pending_slope = (n * sum_xy_pe - sum_x * sum_y_pe) / denom
        result.uncorrectable_slope = (n * sum_xy_un - sum_x * sum_y_un) / denom
        result.temperature_slope = (n * sum_xy_tm - sum_x * sum_y_tm) / denom

        # Set warning flags
        result.reallocated_warn = result.reallocated_slope > THRESHOLD_REALLOCATED
        result.pending_warn = result.pending_slope > THRESHOLD_PENDING
        result.uncorrectable_warn = result.uncorrectable_slope > THRESHOLD_UNCORRECTABLE
        result.temperature_warn = result.temperature_slope > THRESHOLD_TEMPERATURE

        return result

    def get_warning_text(self, disk_path: str) -> str:
        """Get human-readable warning text for a disk trend."""
        trend = self.query_trend(disk_path)
        if not trend:
            return ""

        warnings = []
        if trend.reallocated_warn:
            warnings.append(f"reallocated sectors increasing {trend.reallocated_slope:.1f}/day")
        if trend.pending_warn:
            warnings.append(f"pending sectors increasing {trend.pending_slope:.1f}/day")
        if trend.uncorrectable_warn:
            warnings.append(f"uncorrectable sectors increasing {trend.uncorrectable_slope:.1f}/day")
        if trend.temperature_warn:
            warnings.append(f"temperature rising {trend.temperature_slope:.1f}°C/day")

        return "; ".join(warnings)

    def get_disk_paths(self) -> list[str]:
        """Get all disk paths in the database."""
        if not self.conn:
            return []
        rows = self.conn.execute(
            "SELECT DISTINCT disk_path FROM smart_snapshots"
        ).fetchall()
        return [r[0] for r in rows]

    def get_latest_snapshot(self, disk_path: str) -> Optional[dict]:
        """Get the most recent snapshot for a disk."""
        if not self.conn:
            return None
        row = self.conn.execute(
            """SELECT snapshot_time, reallocated, pending, uncorrectable,
                      temperature, power_on_hours, wear_level, health_score
               FROM smart_snapshots
               WHERE disk_path = ?
               ORDER BY snapshot_time DESC LIMIT 1""",
            (disk_path,),
        ).fetchone()
        if not row:
            return None
        return {
            "snapshot_time": row[0],
            "reallocated": row[1],
            "pending": row[2],
            "uncorrectable": row[3],
            "temperature": row[4],
            "power_on_hours": row[5],
            "wear_level": row[6],
            "health_score": row[7],
        }
