"""Risk engine with simple XAI-style explanation.

This is a lightweight, dependency-free implementation that computes a
risk score [1..10] from feature weights and returns a short explanation
string suitable for audit logs. It's deterministic and intended as a
pluggable component for later replacement by a trained XAI model.

Do NOT treat this as a certified ML model; it's a conservative heuristic
that meets the project need for "justification of why risk is high".
"""

from typing import Dict, Any, Tuple
import math
import json
import logging
import os
import sqlite3
import time

logger = logging.getLogger("risk_engine")


DEFAULT_WEIGHTS = {
    "cnpj_age_days": 0.2,
    "changes_last_30d": 0.3,
    "missing_docs": 0.4,
    "manual_override": 1.5,
}


def compute_risk(
    features: Dict[str, float], weights: Dict[str, float] = None
) -> Tuple[int, str]:
    """Compute integer risk 1-10 and return an explanation string.

    features: numeric features normalized to sensible ranges by caller.
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    # Aggregate weighted sum
    score = 0.0
    contributions = []
    for k, v in features.items():
        wk = w.get(k, 0.0)
        contr = wk * float(v)
        contributions.append((k, float(v), wk, contr))
        score += contr

    # Normalize to 1..10 using a conservative sigmoid-ish mapping
    normalized = 1 + 9 * (1 / (1 + math.exp(-0.6 * (score - 1))))
    risk = min(10, max(1, int(round(normalized))))

    # Short explanation (XAI-like): top 3 contributors
    contributions.sort(key=lambda x: abs(x[3]), reverse=True)
    top = contributions[:3]
    reasons = []
    for k, val, wk, contr in top:
        reasons.append(
            f"{k}={'{:.2f}'.format(val)} x w={'{:.2f}'.format(wk)} => {'{:.2f}'.format(contr)}"
        )

    explanation = json.dumps(
        {"risk": risk, "score_raw": score, "top_reasons": reasons}, ensure_ascii=False
    )
    logger.info("risk_computed %s", explanation)
    return risk, explanation


def justify_high_risk(features: Dict[str, Any]) -> Tuple[int, str]:
    """Wrapper to prepare features and compute risk + explanation.

    Example features accepted (caller can pass only the ones available):
      - cnpj_age_days: older companies usually lower risk (inverse)
      - changes_last_30d: count of critical registry changes
      - missing_docs: fraction [0..1]
      - manual_override: 0/1
    """
    # default normalization
    f = {}
    try:
        age = float(features.get("cnpj_age_days", 365.0))
        f["cnpj_age_days"] = max(0.0, min(1.0, 1.0 - min(age / 3650.0, 1.0)))
        f["changes_last_30d"] = float(features.get("changes_last_30d", 0.0))
        f["missing_docs"] = float(features.get("missing_docs", 0.0))
        f["manual_override"] = 1.0 if features.get("manual_override") else 0.0
    except Exception:
        logger.exception("feature_normalization_failed")
        # fallback safe defaults
        f = {
            "cnpj_age_days": 0.5,
            "changes_last_30d": 0.0,
            "missing_docs": 0.0,
            "manual_override": 0.0,
        }

    return compute_risk(f)


__all__ = ["compute_risk", "justify_high_risk"]


def modulate_speed(calendar_db: str = None) -> float:
    """Return a speed multiplier [0.5..1.5] based on proximity to fiscal due dates.

    If a calendar DB (SQLite) is provided, it should contain a table `due_dates(ts INTEGER)`.
    Multiplier reduces speed (closer to 0.5) when within high-risk windows.
    """
    try:
        now = int(time.time())
        if not calendar_db or not os.path.exists(calendar_db):
            # default conservative multiplier
            return 1.0
        c = sqlite3.connect(calendar_db)
        cur = c.execute("SELECT ts FROM due_dates ORDER BY ts")
        dates = [r[0] for r in cur.fetchall()]
        c.close()
        # find nearest due date within 30 days
        nearest = min(dates, key=lambda d: abs(d - now)) if dates else None
        if not nearest:
            return 1.0
        days = abs(nearest - now) / 86400.0
        if days < 2:
            return 0.5
        if days < 7:
            return 0.75
        if days < 30:
            return 0.9
        return 1.0
    except Exception:
        logger.exception("modulate_speed_failed")
        return 1.0
