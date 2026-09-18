"""Weekday-specific least-squares trends, fitted only to past complete observations."""

from datetime import timedelta
from statistics import mean


def predict(history, horizon=7, population=None):
    if not history:
        return []
    cutoff = history[-1]["date"]
    window = [
        p for p in history if (cutoff - p["date"]).days < 56 and p["active_users"] is not None
    ]
    groups = {
        weekday: [p for p in window if p["date"].weekday() == weekday] for weekday in range(7)
    }
    if len(window) < 28 or any(len(points) < 4 for points in groups.values()):
        return []
    if history[-1]["active_users"] is None:
        return []
    forecast = []
    for ahead in range(1, horizon + 1):
        target = cutoff + timedelta(days=ahead)
        points = groups[target.weekday()]
        xs = [(p["date"] - cutoff).days for p in points]
        ys = [p["active_users"] for p in points]
        center_x, center_y = mean(xs), mean(ys)
        slope = sum((x - center_x) * (y - center_y) for x, y in zip(xs, ys, strict=True)) / sum(
            (x - center_x) ** 2 for x in xs
        )
        value = max(0.0, center_y + slope * (ahead - center_x))
        if population is not None:
            value = min(value, population)
        forecast.append({"date": target, "active_users": round(value, 1)})
    return forecast


def backtest(history, populations=None):
    """Direct J+7 error over up to 14 past targets; no training target leaks into its fit."""
    errors, baseline_errors = [], []
    for target_index in range(max(0, len(history) - 14), len(history)):
        origin = target_index - 7
        if origin < 0 or history[target_index]["active_users"] is None:
            continue
        estimate = predict(
            history[: origin + 1],
            population=populations.get(history[origin]["date"]) if populations else None,
        )
        if not estimate:
            continue
        actual = history[target_index]["active_users"]
        errors.append(abs(actual - estimate[-1]["active_users"]))
        baseline_errors.append(abs(actual - history[origin]["active_users"]))
    return {
        "targets": len(errors),
        "mae": round(mean(errors), 1) if errors else None,
        "baseline_mae": round(mean(baseline_errors), 1) if baseline_errors else None,
    }
