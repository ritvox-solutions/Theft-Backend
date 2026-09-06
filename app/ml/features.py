"""Feature engineering for anomaly scoring. Single source of truth for the
feature vector shape — both train.py and predict.py call extract_features()
so the two can never drift out of sync on column order.
"""

import math

FEATURE_NAMES = [
    "avg_voltage",
    "avg_current",
    "avg_power",
    "power_variance",
    "reading_count",
    "tod_sin",
    "tod_cos",
    "voltage_current_ratio",
    "power_factor_est",
]


def extract_features(window) -> list[float]:
    """Builds the feature vector for one reading_windows row.

    `window` needs: avg_voltage, avg_current, avg_power, power_variance,
    reading_count, window_start. Works on a real ReadingWindow ORM instance
    (persisted or transient) since it only reads plain attributes.
    """
    avg_voltage = float(window.avg_voltage)
    avg_current = float(window.avg_current)
    avg_power = float(window.avg_power)
    power_variance = float(window.power_variance)
    reading_count = float(window.reading_count)

    # Time-of-day as sin/cos rather than a raw hour int, so 23:00 and 00:00
    # are recognized as adjacent instead of maximally far apart.
    hour_of_day = window.window_start.hour + window.window_start.minute / 60
    tod_sin = math.sin(2 * math.pi * hour_of_day / 24)
    tod_cos = math.cos(2 * math.pi * hour_of_day / 24)

    voltage_current_ratio = avg_voltage / avg_current if avg_current else 0.0

    # Not a true cos(phi): Reading.power is always voltage * current with no
    # independent reactive-power measurement (per Phase 2), so there's no real
    # power factor to estimate. This is the ratio of mean(V*I) to mean(V)*mean(I)
    # within the window — ~1.0 for a stable window, and it drifts when the
    # window's V/I samples are unusually volatile or anti-correlated. Kept as a
    # cheap stability signal, not a physical power factor.
    denominator = avg_voltage * avg_current
    power_factor_est = avg_power / denominator if denominator else 0.0

    return [
        avg_voltage,
        avg_current,
        avg_power,
        power_variance,
        reading_count,
        tod_sin,
        tod_cos,
        voltage_current_ratio,
        power_factor_est,
    ]
