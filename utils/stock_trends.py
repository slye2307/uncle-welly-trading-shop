from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Mapping, Optional, Dict, Any, List

import numpy as np


def _lookup(row: Any, key: str) -> Any:
    """
    Safe value accessor that works with dicts, sqlite3.Row, and objects.
    """
    if isinstance(row, Mapping):
        if hasattr(row, "get"):
            return row.get(key)
        if key in row:
            return row[key]
    if hasattr(row, "__getitem__"):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            pass
    return getattr(row, key, None)


def _parse_sale_date(value: Any) -> Optional[datetime]:
    """
    Attempt to parse the sale_date column into a datetime object.
    Supports datetime objects, ISO strings, and common SQLite default formats.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    value_str = str(value)
    # Try ISO parsing first (handles YYYY-MM-DD and YYYY-MM-DDTHH:MM:SS)
    try:
        return datetime.fromisoformat(value_str.replace("Z", "+00:00"))
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value_str, fmt)
        except ValueError:
            continue
    return None


def _aggregate_daily_profit(rows: Iterable[Mapping[str, Any]]) -> Dict[datetime, float]:
    """
    Aggregate per-sale profit rows into a daily total.
    """
    daily = defaultdict(float)
    for row in rows:
        sale_dt = _parse_sale_date(_lookup(row, "sale_date"))
        profit = float(_lookup(row, "profit") or 0)

        if sale_dt is None:
            continue
        sale_day = sale_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        daily[sale_day] += profit
    return dict(daily)


def forecast_profit_trend(
    rows: Iterable[Mapping[str, Any]],
    horizon_days: int = 7,
) -> Dict[str, Any]:
    """
    Lightweight ML utility that fits a simple linear regression to historical
    daily profit totals and projects what the profit might look like after the
    specified horizon.
    """
    daily_profit = _aggregate_daily_profit(rows)
    if len(daily_profit) < 2:
        return {
            "status": "insufficient_data",
            "insight": "More sales history is needed before an AI forecast can be generated.",
            "daily_points": [],
        }

    ordered_points: List[Any] = sorted(daily_profit.items(), key=lambda item: item[0])
    start_date = ordered_points[0][0]
    x = np.array([(point[0] - start_date).days for point in ordered_points], dtype=float)
    y = np.array([point[1] for point in ordered_points], dtype=float)

    if np.allclose(y.std(), 0):
        trend_label = "flat"
        slope = 0.0
        intercept = float(y.mean())
    else:
        slope, intercept = np.polyfit(x, y, 1)
        trend_label = "upward" if slope > 0 else "downward"

    future_x = x[-1] + horizon_days
    projection = float(slope * future_x + intercept)

    trend_strength = float(min(1.0, abs(slope) / (np.std(y) + 1e-6)))
    insight = (
        f"AI expects {trend_label} profits over the next {horizon_days} days "
        f"with a projected total of ~{projection:.2f}."
    )
    if trend_label == "flat":
        insight = (
            "AI expects profits to stay roughly flat over the next "
            f"{horizon_days} days at about {projection:.2f}."
        )

    return {
        "status": "ok",
        "trend_label": trend_label,
        "trend_strength": round(trend_strength, 2),
        "projected_profit": round(projection, 2),
        "horizon_days": horizon_days,
        "insight": insight,
        "daily_points": [
            {"date": point[0].date().isoformat(), "profit": round(point[1], 2)}
            for point in ordered_points
        ],
        "model_details": {
            "slope": round(float(slope), 4),
            "intercept": round(float(intercept), 4),
            "training_points": len(ordered_points),
        },
    }


