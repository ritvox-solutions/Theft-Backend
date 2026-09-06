"""Simulate an ESP32 meter posting readings through the real /api/readings endpoint.

Usage:
    python -m app.scripts.simulate --meter-code MTR-0001 --device-key DEVKEY-0001
    python -m app.scripts.simulate --meter-code MTR-0001 --device-key DEVKEY-0001 --anomalous

Posts through the HTTP API (not a DB shortcut) so it exercises the real ingestion
path, device-key auth included.
"""

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

NORMAL_VOLTAGE = (230, 5)  # mean, stddev
NORMAL_CURRENT = (10, 2)

# Two theft/loss-shaped anomaly patterns, chosen because they're expressible
# through the real ingestion contract (voltage/current only — the server
# computes power itself, so a "power inconsistent with V*I" pattern isn't
# reachable through this endpoint by design).
ANOMALY_PATTERNS = {
    "voltage_sag": {"voltage": (150, 5), "current": (10, 2)},
    "current_spike": {"voltage": (230, 5), "current": (40, 5)},
}


def generate_reading(anomalous: bool) -> tuple[float, float, str | None]:
    if anomalous:
        pattern = random.choice(list(ANOMALY_PATTERNS))
        spec = ANOMALY_PATTERNS[pattern]
        voltage = random.gauss(*spec["voltage"])
        current = random.gauss(*spec["current"])
        return voltage, current, pattern
    voltage = random.gauss(*NORMAL_VOLTAGE)
    current = random.gauss(*NORMAL_CURRENT)
    return voltage, current, None


def post_reading(
    api_url: str, device_key: str, meter_code: str, voltage: float, current: float
) -> tuple[int, str]:
    body = json.dumps(
        {
            "meter_id": meter_code,
            "voltage": round(voltage, 2),
            "current": round(current, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ).encode()
    req = urllib.request.Request(
        f"{api_url}/api/readings",
        data=body,
        headers={"Content-Type": "application/json", "x-device-key": device_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main():
    parser = argparse.ArgumentParser(description="Simulate ESP32 meter readings")
    parser.add_argument("--meter-code", required=True)
    parser.add_argument("--device-key", required=True)
    parser.add_argument("--api-url", default="http://localhost:7000")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between readings")
    parser.add_argument(
        "--anomalous", action="store_true", help="inject voltage-sag/current-spike patterns"
    )
    args = parser.parse_args()

    for i in range(args.count):
        voltage, current, pattern = generate_reading(args.anomalous)
        status_code, body = post_reading(
            args.api_url, args.device_key, args.meter_code, voltage, current
        )
        tag = f" [{pattern}]" if pattern else ""
        print(
            f"[{i + 1}/{args.count}] status={status_code} "
            f"voltage={voltage:.1f} current={current:.1f}{tag} -> {body}"
        )
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
