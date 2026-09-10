import json
import logging
import ssl
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from app.config import (
    MQTT_BROKER,
    MQTT_ENABLED,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_USE_TLS,
    MQTT_USERNAME,
)
from app.database import SessionLocal
from app.models.anomaly import Anomaly, AnomalyStatus
from app.models.meter import Meter
from app.models.reading import Reading
from app.services.aggregation import run_aggregation_task
from app.services.notifications import notify_admins_of_anomaly

logger = logging.getLogger(__name__)

_mqtt_client: mqtt.Client | None = None
_client_lock = threading.Lock()
_last_aggregation_time: dict = {}


def get_mqtt_client() -> mqtt.Client | None:
    return _mqtt_client


def publish_relay_command(meter_code: str, command: str) -> bool:
    """Publish relay state ('connected' or 'disconnected') to the meter's topic."""
    global _mqtt_client
    if _mqtt_client is None or not _mqtt_client.is_connected():
        logger.warning("MQTT client not connected. Cannot publish relay command to %s", meter_code)
        return False

    topic = f"meters/{meter_code}/relay"
    payload = json.dumps({"meter_id": meter_code, "command": command})
    info = _mqtt_client.publish(topic, payload, qos=1)
    logger.info("Published relay command to %s: %s (mid=%s)", topic, payload, info.mid)

    try:
        from app.services.ws_manager import ws_manager
        ws_manager.broadcast_threadsafe(
            {
                "type": "relay_update",
                "meter_code": meter_code,
                "relay_state": command,
            }
        )
    except Exception as e:
        logger.debug("Could not broadcast relay update: %s", e)

    return True


def _process_reading(payload_str: str, topic: str):
    """Parses reading, writes to DB, runs anomaly detection and acts on relay."""
    try:
        data = json.loads(payload_str)
    except Exception as e:
        logger.error("Failed to parse JSON on topic %s: %s", topic, e)
        return

    meter_code = data.get("meter_id")
    if not meter_code:
        parts = topic.split("/")
        if len(parts) >= 2:
            meter_code = parts[1]

    voltage = float(data.get("voltage", 0.0))
    current = float(data.get("current", 0.0))
    source_current = float(data.get("source_current", current))
    delta_current = float(data.get("delta_current", max(0.0, source_current - current)))
    theft_detected = bool(data.get("theft_detected", False))

    from app.config import CURRENT_NOISE_DEADBAND, THEFT_CURRENT_THRESHOLD

    # Clean ambient ADC noise:
    if current < CURRENT_NOISE_DEADBAND:
        current = 0.0
    if source_current < CURRENT_NOISE_DEADBAND:
        source_current = 0.0
    if voltage < 30.0:
        voltage = 0.0

    delta_current = round(max(0.0, source_current - current), 3)
    if delta_current >= THEFT_CURRENT_THRESHOLD:
        theft_detected = True

    current = round(current, 3)
    source_current = round(source_current, 3)
    voltage = round(voltage, 1)
    power = round(voltage * current, 2)
    now_utc = datetime.now(timezone.utc)
    ts_str = data.get("timestamp")
    if ts_str:
        try:
            recorded_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            # If device clock is drifting by more than 3s, use accurate server reception time
            if abs((now_utc - recorded_at).total_seconds()) > 3.0:
                recorded_at = now_utc
        except Exception:
            recorded_at = now_utc
    else:
        recorded_at = now_utc

    db = SessionLocal()
    try:
        meter = db.query(Meter).filter(Meter.meter_code == meter_code).first()
        if not meter:
            logger.warning("Meter with code %s not found in database", meter_code)
            return

        # 1. Insert Reading with dual current measurements
        reading = Reading(
            meter_id=meter.id,
            voltage=voltage,
            current=current,
            source_current=source_current,
            delta_current=delta_current,
            power=power,
            recorded_at=recorded_at,
        )
        db.add(reading)
        db.commit()
        db.refresh(reading)
        logger.info("Saved reading %s for meter %s: V=%.1f, I=%.3f, Delta=%.3f", reading.id, meter_code, voltage, current, delta_current)

        # Broadcast reading immediately to connected WebSocket clients (<10ms)
        try:
            from app.services.ws_manager import ws_manager
            ws_manager.broadcast_threadsafe(
                {
                    "type": "reading",
                    "meter_id": str(meter.id),
                    "meter_code": meter.meter_code,
                    "reading": {
                        "id": str(reading.id),
                        "meter_id": str(meter.id),
                        "voltage": float(reading.voltage),
                        "current": float(reading.current),
                        "source_current": float(reading.source_current or 0.0),
                        "delta_current": float(reading.delta_current or 0.0),
                        "theft_detected": theft_detected,
                        "power": float(reading.power),
                        "recorded_at": reading.recorded_at.isoformat(),
                        "created_at": reading.created_at.isoformat() if reading.created_at else reading.recorded_at.isoformat(),
                    },
                    "theft_detected": theft_detected,
                    "relay_state": meter.relay_state.value if hasattr(meter.relay_state, "value") else str(meter.relay_state),
                },
                target_meter_id=meter.id,
            )
        except Exception as e:
            logger.debug("Failed to broadcast reading over WebSocket: %s", e)

        # 2. Check if DB already requires disconnect
        if meter.relay_state == "disconnected":
            publish_relay_command(meter.meter_code, "disconnected")

        # 3. Ensure a ReadingWindow exists for this timestamp
        from datetime import timedelta
        from app.models.reading_window import ReadingWindow
        from app.services.aggregation import floor_to_window, WINDOW_MINUTES
        from app.services.anomalies import create_anomaly_if_missing

        window_start = floor_to_window(recorded_at)
        window = (
            db.query(ReadingWindow)
            .filter(
                ReadingWindow.meter_id == meter.id,
                ReadingWindow.window_start == window_start,
            )
            .first()
        )
        if window is None:
            window = ReadingWindow(
                meter_id=meter.id,
                window_start=window_start,
                window_end=window_start + timedelta(minutes=WINDOW_MINUTES),
                avg_voltage=voltage,
                avg_current=current,
                avg_power=power,
                power_variance=0.0,
                reading_count=1,
                energy_kwh=(power * (WINDOW_MINUTES / 60)) / 1000,
                is_anomaly=False,
                anomaly_score=None,
                scored_at=None,
            )
            db.add(window)
            db.flush()

        # 4. If hardware differential theft is detected, register anomaly immediately
        if theft_detected and delta_current >= THEFT_CURRENT_THRESHOLD:
            window.is_anomaly = True
            window.anomaly_score = 0.99
            window.scored_at = datetime.now(timezone.utc)
            db.flush()

            anomaly = create_anomaly_if_missing(
                db,
                window,
                0.99,
                notes=f"Physical line tap detected: {delta_current:.3f}A bypassing junction box (Source={source_current:.3f}A, Metered={current:.3f}A).",
            )
            if anomaly:
                try:
                    from app.services.ws_manager import ws_manager
                    ws_manager.broadcast_threadsafe(
                        {
                            "type": "anomaly",
                            "meter_id": str(meter.id),
                            "meter_code": meter.meter_code,
                            "anomaly": {
                                "id": str(anomaly.id),
                                "meter_id": str(meter.id),
                                "meter_code": meter.meter_code,
                                "anomaly_score": float(anomaly.anomaly_score),
                                "status": anomaly.status.value if hasattr(anomaly.status, "value") else str(anomaly.status),
                                "detected_at": anomaly.detected_at.isoformat(),
                                "notes": anomaly.notes,
                            },
                        }
                    )
                except Exception as ws_err:
                    logger.debug("Failed to broadcast anomaly over WebSocket: %s", ws_err)

        db.commit()

        # Trigger background aggregation for historical rollup (throttled to at most once per 60s per meter)
        import time
        now_ts = time.time()
        if meter.id not in _last_aggregation_time or (now_ts - _last_aggregation_time[meter.id] > 60):
            _last_aggregation_time[meter.id] = now_ts
            threading.Thread(target=run_aggregation_task, args=(meter.id,), daemon=True).start()

    except Exception as e:
        logger.exception("Error processing reading for %s: %s", meter_code, e)
    finally:
        db.close()


def _on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("Connected to MQTT broker %s:%s", MQTT_BROKER, MQTT_PORT)
        client.subscribe("meters/+/readings", qos=1)
        logger.info("Subscribed to topic: meters/+/readings")
    else:
        logger.error("Failed to connect to MQTT broker, return code: %d", rc)


def _on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8")
    logger.info("Received MQTT message on %s: %s", msg.topic, payload)
    threading.Thread(target=_process_reading, args=(payload, msg.topic), daemon=True).start()


def start_mqtt():
    """Starts the background MQTT client loop."""
    global _mqtt_client
    if not MQTT_ENABLED:
        logger.info("MQTT service is disabled via MQTT_ENABLED=false")
        return

    with _client_lock:
        if _mqtt_client is not None:
            return

        client_id = f"gridwatch-backend-{int(datetime.now().timestamp())}"
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)

        if MQTT_USERNAME and MQTT_PASSWORD:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        if MQTT_USE_TLS:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        client.on_connect = _on_connect
        client.on_message = _on_message

        try:
            logger.info("Connecting to MQTT broker at %s:%d ...", MQTT_BROKER, MQTT_PORT)
            client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_start()
            _mqtt_client = client
        except Exception as e:
            logger.error("Could not start MQTT client: %s", e)


def stop_mqtt():
    """Stops the MQTT client loop."""
    global _mqtt_client
    with _client_lock:
        if _mqtt_client is not None:
            try:
                _mqtt_client.loop_stop()
                _mqtt_client.disconnect()
            except Exception as e:
                logger.error("Error disconnecting MQTT: %s", e)
            _mqtt_client = None
            logger.info("MQTT client stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_mqtt()
    print("MQTT service running. Press Ctrl+C to stop.")
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_mqtt()
