import json, time, logging, struct, hashlib
from kafka import KafkaConsumer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("qdrant-indexer")

KAFKA_BROKER = "redpanda.aiot.svc.cluster.local:9092"
QDRANT_URL = "http://qdrant.aiot.svc.cluster.local:6333"
VECTOR_SIZE = 64
BATCH_SIZE = 1000
COLLECTION = "sensor_history"

def safe_deserialize(x):
    try:
        return json.loads(x.decode("utf-8"))
    except Exception:
        return None

def fast_embed(text):
    """4x sha256 digesty = 128 bajtov = 32 floatov × 2 = 64 floatov, 1 hash volanie namiesto 64"""
    b = text.encode()
    raw = b''
    for salt in (b'\x00', b'\x01', b'\x02', b'\x03'):
        raw += hashlib.sha256(salt + b).digest()  # 32B × 4 = 128B
        if len(raw) >= VECTOR_SIZE * 4:
            break
    # Interpret 256 bytes as 64 floats via simple int conversion
    vec = []
    for i in range(VECTOR_SIZE):
        val = (raw[i*2] << 8 | raw[i*2+1]) / 65535.0 * 2 - 1
        vec.append(val)
    # Normalize
    norm = sum(x*x for x in vec) ** 0.5
    return [x/norm for x in vec] if norm > 0 else vec

qdrant = QdrantClient(url=QDRANT_URL, timeout=60)

for attempt in range(10):
    try:
        collections = [c.name for c in qdrant.get_collections().collections]
        if COLLECTION not in collections:
            qdrant.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
            )
            log.info(f"Collection {COLLECTION} created")
        else:
            log.info(f"Collection {COLLECTION} exists")
        break
    except Exception as e:
        log.warning(f"Collection setup attempt {attempt+1}/10: {e}")
        time.sleep(5)
else:
    log.error("Failed to setup collection")
    import sys; sys.exit(1)

consumer = KafkaConsumer(
    "telemetry",
    bootstrap_servers=KAFKA_BROKER,
    value_deserializer=safe_deserialize,
    group_id="qdrant-indexer-group4",
    auto_offset_reset="latest",
    max_poll_records=1000,
    fetch_max_bytes=10485760
)

log.info(f"Qdrant indexer v2 — batch={BATCH_SIZE}, fast_embed, async")
point_id = int(time.time() * 1000000)
count = 0
batch_points = []
t0 = time.time()

for msg in consumer:
    data = msg.value
    if data is None:
        continue
    try:
        payload = data.get("payload", {})
        topic = data.get("topic", "unknown")
        sid = payload.get("sensor_id") or payload.get("machine_id", "unknown")
        loc = payload.get("location") or payload.get("machine_type", "unknown")
        val = payload.get("value") or payload.get("temperature", 0)
        unit = payload.get("unit") or payload.get("status", "")

        text = f"{sid} {loc} {val} {unit} {topic}"
        embedding = fast_embed(text)

        batch_points.append(PointStruct(
            id=point_id, vector=embedding,
            payload={"text": f"Sensor {sid} at {loc}: {val} {unit} [{topic}]",
                     "sensor_id": sid, "topic": topic, "timestamp": time.time()}
        ))
        point_id += 1

        if len(batch_points) >= BATCH_SIZE:
            qdrant.upsert(collection_name=COLLECTION, points=batch_points, wait=False)
            count += len(batch_points)
            elapsed = time.time() - t0
            rate = count / elapsed if elapsed > 0 else 0
            if count % 5000 < BATCH_SIZE:
                log.info(f"Indexed {count} | rate={rate:.0f}/s")
            batch_points = []

    except Exception as e:
        log.error(f"Error: {e}")
        batch_points = []
