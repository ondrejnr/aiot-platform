import hashlib
import json
import logging
import os
import threading
import time
from typing import List

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("qdrant-indexer")


def parse_host_port(host_value, port_value, default_host, default_port):
    host = host_value or default_host
    port = port_value or str(default_port)
    if isinstance(host, str) and host.startswith("tcp://"):
        host = host.removeprefix("tcp://")
        if ":" in host:
            host, inferred_port = host.rsplit(":", 1)
            port = inferred_port
    if isinstance(port, str) and port.startswith("tcp://"):
        port = port.removeprefix("tcp://")
        if ":" in port:
            host, port = port.rsplit(":", 1)
    return host, int(port)

MQTT_HOST = os.getenv("MQTT_HOST", "emqx.emqx.svc.cluster.local")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "sensors/#")
QDRANT_HOST, QDRANT_PORT = parse_host_port(
    os.getenv("QDRANT_HOST"),
    os.getenv("QDRANT_PORT"),
    "qdrant.aiot.svc.cluster.local",
    6333,
)
COLLECTION = os.getenv("QDRANT_COLLECTION", "sensor_history")
RETENTION_SECS = int(os.getenv("RETENTION_SECS", "3600"))
MAX_POINTS = int(os.getenv("MAX_POINTS", "50000"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "64"))
FLUSH_INTERVAL = float(os.getenv("FLUSH_INTERVAL", "2"))

qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=30)
buffer = []
buffer_lock = threading.Lock()


def fast_embed(text):
    raw_text = text.encode("utf-8")
    raw = b""
    for salt in (b"\x00", b"\x01", b"\x02", b"\x03"):
        raw += hashlib.sha256(salt + raw_text).digest()
        if len(raw) >= 64 * 4:
            break
    vector = []
    for index in range(64):
        value = (raw[index * 2] << 8 | raw[index * 2 + 1]) / 65535.0 * 2 - 1
        vector.append(value)
    norm = sum(value * value for value in vector) ** 0.5
    return [value / norm for value in vector] if norm > 0 else vector


def ensure_collection():
    collections = {item.name for item in qdrant.get_collections().collections}
    if COLLECTION not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=qmodels.VectorParams(size=64, distance=qmodels.Distance.COSINE),
        )
        qdrant.create_payload_index(COLLECTION, "machine_id", qmodels.PayloadSchemaType.KEYWORD)
        qdrant.create_payload_index(COLLECTION, "machine_type", qmodels.PayloadSchemaType.KEYWORD)
        qdrant.create_payload_index(COLLECTION, "location", qmodels.PayloadSchemaType.KEYWORD)
        qdrant.create_payload_index(COLLECTION, "ts", qmodels.PayloadSchemaType.FLOAT)
        log.info("Created Qdrant collection %s", COLLECTION)


def infer_location(payload, topic):
    if payload.get("location"):
        return payload["location"]
    parts = topic.split("/")
    if len(parts) >= 2:
        return parts[1]
    return "unknown"


def infer_machine_type(machine_id, payload, topic):
    if payload.get("machine_type"):
        return payload["machine_type"]
    if machine_id and "-" in machine_id:
        return machine_id.rsplit("-", 1)[0]
    parts = topic.split("/")
    if len(parts) >= 3:
        return parts[2]
    return "unknown"


def text_for_embedding(payload, machine_id, machine_type, location):
    return (
        f"machine {machine_id} type {machine_type} location {location} "
        f"temperature {payload.get('temperature')} vibration {payload.get('vibration')} "
        f"pressure {payload.get('pressure')} rpm {payload.get('rpm')} humidity {payload.get('humidity')} "
        f"status {payload.get('status')} anomaly {payload.get('anomaly_score')}"
    )


def point_id(machine_id, ts_value, payload):
    raw = json.dumps([machine_id, ts_value, payload], sort_keys=True)
    return int(hashlib.sha1(raw.encode("utf-8")).hexdigest()[:15], 16)


def build_points(items: List[dict]):
    points = []
    for item in items:
        points.append(
            qmodels.PointStruct(
                id=item["id"],
                vector=fast_embed(item["text"]),
                payload=item["payload"],
            )
        )
    return points


def flush_items(items):
    if not items:
        return
    qdrant.upsert(collection_name=COLLECTION, points=build_points(items), wait=False)
    log.info("Upserted %s Qdrant points", len(items))


def flush_loop():
    while True:
        time.sleep(FLUSH_INTERVAL)
        items = []
        with buffer_lock:
            if buffer:
                items = buffer[:BATCH_SIZE]
                del buffer[: len(items)]
        if items:
            try:
                flush_items(items)
            except Exception as exc:
                log.error("Qdrant flush error: %s", exc)
                with buffer_lock:
                    buffer[:0] = items
                    if len(buffer) > BATCH_SIZE * 20:
                        del buffer[BATCH_SIZE * 20 :]


def cleanup_loop():
    while True:
        try:
            cutoff = time.time() - RETENTION_SECS
            qdrant.delete(
                collection_name=COLLECTION,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[qmodels.FieldCondition(key="ts", range=qmodels.Range(lt=cutoff))]
                    )
                ),
                wait=False,
            )
            count = qdrant.count(COLLECTION, exact=False).count
            if count > MAX_POINTS:
                log.warning("Qdrant point count high: %s", count)
        except Exception as exc:
            log.error("Cleanup error: %s", exc)
        time.sleep(60)


def on_connect(client, _userdata, _flags, reason_code, _properties=None):
    if reason_code == 0:
        client.subscribe(MQTT_TOPIC)
        log.info("MQTT connected, subscribed to %s", MQTT_TOPIC)
    else:
        log.error("MQTT connect failed with reason %s", reason_code)


def on_message(_client, _userdata, message):
    try:
        data = json.loads(message.payload.decode("utf-8"))
        payload = data.get("payload", data) if isinstance(data, dict) else {}
        machine_id = payload.get("machine_id") or payload.get("sensor_id", "unknown")
        machine_type = infer_machine_type(machine_id, payload, message.topic)
        location = infer_location(payload, message.topic)
        ts_raw = payload.get("ts")
        if isinstance(ts_raw, (int, float)):
            ts_value = float(ts_raw)
        elif isinstance(ts_raw, str):
            try:
                ts_value = float(ts_raw)
            except ValueError:
                from datetime import datetime
                ts_value = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
        else:
            ts_value = time.time()
        item_payload = {
            "machine_id": machine_id,
            "machine_type": machine_type,
            "location": location,
            "topic": message.topic,
            "ts": ts_value,
            "status": payload.get("status"),
            "temperature": payload.get("temperature"),
            "vibration": payload.get("vibration"),
            "pressure": payload.get("pressure"),
            "rpm": payload.get("rpm"),
            "humidity": payload.get("humidity"),
            "anomaly_score": payload.get("anomaly_score"),
            "raw": payload,
        }
        item = {
            "id": point_id(machine_id, ts_value, payload),
            "text": text_for_embedding(payload, machine_id, machine_type, location),
            "payload": item_payload,
        }
        with buffer_lock:
            buffer.append(item)
            if len(buffer) >= BATCH_SIZE:
                items = buffer[:BATCH_SIZE]
                del buffer[:BATCH_SIZE]
            else:
                items = None
        if items:
            flush_items(items)
    except Exception as exc:
        log.error("MQTT message error: %s", exc)


def mqtt_loop():
    while True:
        try:
            client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id="qdrant-indexer")
            client.on_connect = on_connect
            client.on_message = on_message
            client.reconnect_delay_set(min_delay=1, max_delay=10)
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            log.error("MQTT loop error: %s", exc)
            time.sleep(5)


ensure_collection()
threading.Thread(target=flush_loop, daemon=True).start()
threading.Thread(target=cleanup_loop, daemon=True).start()
log.info("Qdrant indexer MQTT mode")
mqtt_loop()
