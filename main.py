"""Forecast GTA VI's launch-day Twitch viewers, hour by hour.

Entry for make.fun's gta6-twitch-ccu-forecast-01 (program/v1, Python 3.13,
standard library only, no network). Reads one case from the input directory
and writes, for each of hours 2..24 of the release day, five quantiles of
that hour's Twitch category viewer count.

The idea
--------
A launch day's audience curve has a shape that repeats across big game
launches: a spike in the first hour (the midnight-local unlock), a dip while
most of the world sleeps, a jump when the US east coast unlocks, a midday
trough, then a long climb into the evening peak as Europe and the US are
both awake. The *level* of the curve is anchored by the case's own hour-1
print; the *shape* is learned at run time from the case's own
``comparables`` -- the hourly curves of past big launches the kit ships
inside every case -- so nothing about any one launch is baked in.

For every comparable launch with a usable release day we take, per hour h,
the log ratio ``ln(viewers_h / viewers_1)``. Big launches and small launches
do not share one shape: a launch whose first hour is small (its category
barely existed before release) surges far more into the evening than a
launch whose first hour is already huge. So for each hour we fit a short
regression of the log ratio on the log of the launch's hour-1 size across
the comparables, and read it off at this case's hour-1 size:

    log-ratio(h) ~= a_h + b_h * ln(hour-1 viewers)

The residuals of that fit give the predictive spread: their interquartile
range, turned into a log-scale standard deviation, widens the five
quantiles the further out the hour is. Both the median curve and the spread
curve are lightly smoothed across neighbouring hours, because a real
audience curve does not zig-zag hour to hour.

Comparables are filtered before fitting: a launch counts only if its
hour-1 print is at least 10,000 viewers (smaller ones have ratios driven
by near-zero denominators, not by audience behaviour) and only if its
unlock note does not mark it early-access-contaminated, weak, or the
target's own pre-release history. The fitted slope is clamped to
[-1.5, 0.5] and the size we evaluate at is clamped to the sizes actually
seen, so a record-breaking GTA VI hour 1 never extrapolates the line off
a cliff -- it behaves like the biggest launch on record.

If the comparables cannot support a fit at all (too few usable launches),
the program falls back to the median log ratio across whatever is there,
and if there is nothing at all it falls back to persistence: every hour
stays at the hour-1 print with a spread that widens like a random walk.
The program never crashes on a malformed case: any failure to forecast a
case degrades to that persistence forecast, because an invalid case costs
far more than a mediocre one.

Output: {"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]},
exactly 23 rows, hours 2..24, quantiles strictly non-decreasing and above
zero. Deterministic: the same case always writes the same bytes.
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at those levels.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

# A comparable launch needs an hour-1 print at least this big to be trusted:
# below it the log ratios are dominated by a near-zero denominator.
MIN_HOUR1 = 10000.0
# The regression slope of log-ratio on log hour-1 size is kept in this box.
SLOPE_MIN = -1.5
SLOPE_MAX = 0.5
# The predictive log-spread is kept in this box (nats).
SPREAD_MIN = 0.12
SPREAD_MAX = 1.2
# Spread used when a fit has too few points to estimate one.
FALLBACK_SPREAD = 0.30
# Persistence fallback spread: random-walk widening, as the house baseline.
PERSIST_SIGMA = 0.15
HOURS = list(range(2, 25))


def _parse_time(text):
    """Parse an ISO-8601 UTC timestamp; None when it does not parse."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _tier_ok(unlock):
    """True unless the unlock note marks the launch unusable as a shape.

    The notes carry a "Tier: ..." marker. Early-access launches peaked days
    before their nominal release day, weak analogues are free-to-play or
    slow-burn launches, and the target-history entry is GTA VI's own
    pre-release category, which has no release day at all. Anything without
    a marker is a plain comparable.
    """
    if not isinstance(unlock, str):
        return True
    low = unlock.lower()
    return ("early-access-contaminated" not in low
            and "tier: weak" not in low
            and "tier: target-history" not in low)


def launch_curves(case):
    """Usable comparables as (log hour-1 viewers, {hour: log ratio}).

    A comparable's release day is the UTC day of its ``day_start``; hour 1
    is the [00:00, 01:00) point of that day. Hours with no point, or a
    non-positive count, are simply missing for that launch.
    """
    curves = []
    for comp in case.get("comparables") or []:
        if not isinstance(comp, dict):
            continue
        if not _tier_ok(comp.get("unlock")):
            continue
        day_start = _parse_time(comp.get("day_start"))
        if day_start is None:
            continue
        by_hour = {}
        for point in comp.get("hourly") or []:
            if not isinstance(point, dict):
                continue
            at = _parse_time(point.get("from"))
            viewers = point.get("viewers")
            if at is None or not isinstance(viewers, (int, float)):
                continue
            offset = (at - day_start).total_seconds() / 3600.0
            if offset < 0 or offset >= 24 or offset != int(offset):
                continue
            if viewers > 0:
                by_hour[int(offset) + 1] = float(viewers)
        first = by_hour.get(1)
        if first is None or first < MIN_HOUR1:
            continue
        ratios = {}
        for hour in HOURS:
            value = by_hour.get(hour)
            if value is not None:
                ratios[hour] = math.log(value / first)
        if ratios:
            curves.append((math.log(first), ratios))
    return curves


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _quantile(ordered, q):
    """Linear-interpolation quantile of an already-sorted list."""
    n = len(ordered)
    if n == 1:
        return ordered[0]
    pos = q * (n - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return ordered[low]
    return ordered[low] * (high - pos) + ordered[high] * (pos - low)


def _smooth(series):
    """Three-point moving average over hours 2..24, edges averaged over two."""
    hours = sorted(series)
    out = {}
    for i, hour in enumerate(hours):
        neighbours = [series[h] for h in hours[max(0, i - 1):i + 2]]
        out[hour] = sum(neighbours) / len(neighbours)
    return out


def fit_shape(curves, log_size):
    """Per-hour (median log ratio, log spread) from the comparable curves.

    Fits log-ratio ~ a + b * log(hour-1 size) by least squares per hour,
    evaluated at this case's size (clamped to the sizes actually seen).
    The spread is the interquartile range of the fit's residuals, scaled
    to a normal standard deviation.
    """
    median = {}
    spread = {}
    for hour in HOURS:
        xs = []
        ys = []
        for log_first, ratios in curves:
            if hour in ratios:
                xs.append(log_first)
                ys.append(ratios[hour])
        n = len(xs)
        if n == 0:
            median[hour] = 0.0
            spread[hour] = FALLBACK_SPREAD
            continue
        if n < 8:
            median[hour] = _median(ys)
            spread[hour] = FALLBACK_SPREAD
            continue
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        sxx = sum((x - mean_x) ** 2 for x in xs)
        sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        slope = sxy / sxx if sxx > 0 else 0.0
        slope = max(SLOPE_MIN, min(SLOPE_MAX, slope))
        intercept = mean_y - slope * mean_x
        at = max(min(xs), min(max(xs), log_size))
        # Never forecast a shape no past launch ever showed: keep the
        # fitted median inside the observed log-ratio range for the hour.
        # With the size clamped above this only binds on a wild fit, but a
        # record-breaking launch is exactly when a wild fit would hurt.
        median[hour] = max(min(ys), min(max(ys), intercept + slope * at))
        residuals = sorted(y - (intercept + slope * x)
                           for x, y in zip(xs, ys))
        iqr = _quantile(residuals, 0.75) - _quantile(residuals, 0.25)
        spread[hour] = max(SPREAD_MIN, min(SPREAD_MAX, iqr / 1.349))
    return _smooth(median), _smooth(spread)


def persistence_rows(first_print):
    """Fallback forecast: every hour at the hour-1 print, widening spread."""
    rows = []
    for hour in HOURS:
        sigma = PERSIST_SIGMA * math.sqrt(hour - 1)
        rows.append({
            "hour": hour,
            "q": [round(max(1.0, first_print * math.exp(z * sigma)), 2)
                  for z in Z],
        })
    return rows


def forecast_case(case, name):
    """Forecast one case; never raises -- falls back to persistence."""
    try:
        known = case.get("known") or []
        first_row = next((k for k in known
                          if isinstance(k, dict) and k.get("hour") == 1),
                         None)
        first = 1.0
        if first_row is not None:
            viewers = first_row.get("viewers")
            if isinstance(viewers, (int, float)) and viewers > 0:
                first = float(viewers)
        curves = launch_curves(case)
        if not curves:
            return {"hours": persistence_rows(first)}
        median, spread = fit_shape(curves, math.log(first))
        rows = []
        for hour in HOURS:
            quantiles = []
            for z in Z:
                value = first * math.exp(median[hour] + z * spread[hour])
                quantiles.append(round(max(1.0, value), 2))
            # Keep the row non-decreasing even after rounding.
            for i in range(1, len(quantiles)):
                if quantiles[i] < quantiles[i - 1]:
                    quantiles[i] = quantiles[i - 1]
            rows.append({"hour": hour, "q": quantiles})
        return {"hours": rows}
    except Exception:
        # A forecast that is merely mediocre still scores; a crash scores
        # the case as if every quantile equalled the hour-1 print and takes
        # the entry out of the prizes entirely. Degrade, never die.
        try:
            known = case.get("known") or []
            first_row = next((k for k in known
                              if isinstance(k, dict) and k.get("hour") == 1),
                             None)
            first = 1.0
            if first_row is not None:
                viewers = first_row.get("viewers")
                if isinstance(viewers, (int, float)) and viewers > 0:
                    first = float(viewers)
        except Exception:
            first = 1.0
        return {"hours": persistence_rows(first)}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
