import json, time, logging, threading
from kafka import KafkaConsumer
from flask import Flask, jsonify
import redis

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("digital-twin")

KAFKA_BROKER = "redpanda.aiot.svc.cluster.local:9092"
r = redis.Redis(host="redis-master.aiot.svc.cluster.local", port=6379, db=4, decode_responses=True)
bank = redis.Redis(host="redis-master.aiot.svc.cluster.local", port=6379, db=5, decode_responses=True)
app = Flask(__name__)
BANK_TTL = 3600

LIMITS = {
    "pump":       {"temperature": (20,60),  "vibration": (0,2.0), "pressure": (70,115), "rpm": (800,1800)},
    "compressor": {"temperature": (20,80),  "vibration": (0,3.0), "pressure": (70,150), "rpm": (800,2000)},
    "motor":      {"temperature": (20,75),  "vibration": (0,2.5), "pressure": (0,999),  "rpm": (500,2500)},
    "conveyor":   {"temperature": (20,50),  "vibration": (0,1.5), "pressure": (0,999),  "rpm": (200,1200)},
    "turbine":    {"temperature": (20,100), "vibration": (0,4.0), "pressure": (70,200), "rpm": (1000,3500)},
    "generator":  {"temperature": (20,90),  "vibration": (0,3.0), "pressure": (60,160), "rpm": (800,2200)},
}

def check_metrics(machine_type, payload):
    limits = LIMITS.get(machine_type, {})
    violations = []
    for metric, (mn, mx) in limits.items():
        val = payload.get(metric)
        if val is None: continue
        val = float(val)
        if val > mx: violations.append({"metric": metric, "value": round(val,2), "limit": mx, "type": "HIGH"})
        elif val < mn: violations.append({"metric": metric, "value": round(val,2), "limit": mn, "type": "LOW"})
    return violations

def get_status(violations, anomaly_score):
    if float(anomaly_score or 0) > 0.7: return "CRITICAL"
    if len(violations) >= 2: return "CRITICAL"
    if len(violations) == 1: return "WARNING"
    return "OK"

def write_bank_batch(pipe_bank, machine_id, twin, status, violations, anomaly_score, payload):
    pipe_bank.setex(f"bank:machines:{machine_id}", BANK_TTL, json.dumps(twin))
    h = {"temperature": payload.get("temperature"), "vibration": payload.get("vibration"),
         "pressure": payload.get("pressure"), "rpm": payload.get("rpm"),
         "humidity": payload.get("humidity"), "anomaly_score": float(anomaly_score),
         "status": status, "ts": time.time()}
    pipe_bank.lpush(f"bank:history:{machine_id}", json.dumps(h))
    pipe_bank.ltrim(f"bank:history:{machine_id}", 0, 59)
    pipe_bank.expire(f"bank:history:{machine_id}", BANK_TTL)
    if status != "OK":
        alert = {"machine_id": machine_id, "machine_type": twin.get("machine_type",""),
                 "status": status, "violations": violations, "anomaly_score": float(anomaly_score),
                 "metrics": twin["metrics"], "ts": time.time()}
        pipe_bank.lpush("bank:alerts", json.dumps(alert))
        pipe_bank.ltrim("bank:alerts", 0, 99)
        pipe_bank.expire("bank:alerts", BANK_TTL)

def update_bank_summary():
    try:
        cursor = 0
        machines = {}
        while True:
            cursor, keys = bank.scan(cursor, match="bank:machines:*", count=200)
            if keys:
                values = bank.mget(keys)
                for k, v in zip(keys, values):
                    if v: machines[k.replace("bank:machines:","")] = json.loads(v)
            if cursor == 0: break
        critical = [k for k,v in machines.items() if v.get("status")=="CRITICAL"]
        warning = [k for k,v in machines.items() if v.get("status")=="WARNING"]
        ok = [k for k,v in machines.items() if v.get("status")=="OK"]
        s = {"total": len(machines), "ok": len(ok), "warning": len(warning), "critical": len(critical),
             "critical_machines": critical, "warning_machines": warning, "ok_machines": ok, "ts": time.time()}
        bank.setex("bank:summary", BANK_TTL, json.dumps(s))
    except Exception as e:
        log.error(f"Bank summary error: {e}")

BATCH_SIZE = 100
BATCH_TIMEOUT = 0.5
summary_counter = 0

def consume():
    global summary_counter
    consumer = KafkaConsumer("telemetry", bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda x: json.loads(x.decode("utf-8")),
        group_id="digital-twin-group4", auto_offset_reset="latest",
        max_poll_records=500, fetch_max_bytes=5242880)
    log.info("Digital twin v3 (batched pipeline) started")
    prev_status_cache = {}

    while True:
        try:
            records = consumer.poll(timeout_ms=500, max_records=BATCH_SIZE)
            if not records:
                continue
            pipe_r = r.pipeline(transaction=False)
            pipe_bank = bank.pipeline(transaction=False)
            count = 0
            for tp, messages in records.items():
                for msg in messages:
                    data = msg.value
                    payload = data.get("payload", {})
                    machine_id = payload.get("machine_id") or payload.get("sensor_id", "unknown")
                    machine_type = payload.get("machine_type") or payload.get("location", "unknown")
                    anomaly_score = float(payload.get("anomaly_score") or 0)
                    violations = check_metrics(machine_type, payload)
                    status = get_status(violations, anomaly_score)
                    twin = {"machine_id": machine_id, "machine_type": machine_type, "status": status,
                            "violations": violations, "metrics": {"temperature": payload.get("temperature"),
                            "vibration": payload.get("vibration"), "pressure": payload.get("pressure"),
                            "rpm": payload.get("rpm"), "humidity": payload.get("humidity"),
                            "anomaly_score": anomaly_score}, "limits": LIMITS.get(machine_type, {}),
                            "topic": data.get("topic",""), "updated_at": time.time()}
                    pipe_r.hset("digital-twin:machines", machine_id, json.dumps(twin))
                    prev_status = prev_status_cache.get(machine_id, "OK")
                    if status != "OK" and status != prev_status:
                        alert = {"machine_id": machine_id, "machine_type": machine_type, "status": status,
                                 "violations": violations, "anomaly_score": anomaly_score,
                                 "metrics": twin["metrics"], "ts": time.time()}
                        pipe_r.lpush("digital-twin:alerts", json.dumps(alert))
                        pipe_r.ltrim("digital-twin:alerts", 0, 49)
                        log.warning(f"ALERT {status}: {machine_id}")
                    prev_status_cache[machine_id] = status
                    write_bank_batch(pipe_bank, machine_id, twin, status, violations, anomaly_score, payload)
                    count += 1

            pipe_r.expire("digital-twin:machines", 7200)
            pipe_r.expire("digital-twin:alerts", 7200)
            pipe_r.setex("digital-twin:last-update", 60, str(time.time()))
            pipe_r.execute()
            pipe_bank.execute()

            summary_counter += count
            if summary_counter >= 500:
                update_bank_summary()
                summary_counter = 0

            consumer.commit()
        except Exception as e:
            log.error(f"Consume error: {e}")

@app.route("/twin")
def get_twin():
    machines = r.hgetall("digital-twin:machines")
    result = {k: json.loads(v) for k, v in machines.items()}
    critical = [k for k,v in result.items() if v["status"]=="CRITICAL"]
    warning = [k for k,v in result.items() if v["status"]=="WARNING"]
    return jsonify({"count": len(result), "critical": len(critical), "warning": len(warning),
                    "ok": len(result)-len(critical)-len(warning), "machines": result})

@app.route("/twin/<machine_id>")
def get_machine(machine_id):
    data = r.hget("digital-twin:machines", machine_id)
    if not data: return jsonify({"error": "not found"}), 404
    return jsonify(json.loads(data))

@app.route("/alerts")
def get_alerts():
    alerts = r.lrange("digital-twin:alerts", 0, 49)
    return jsonify({"count": len(alerts), "alerts": [json.loads(a) for a in alerts]})

@app.route("/bank/summary")
def bank_summary():
    raw = bank.get("bank:summary")
    if not raw: return jsonify({"error": "no data"}), 404
    return jsonify(json.loads(raw))

@app.route("/bank/machine/<machine_id>")
def bank_machine(machine_id):
    raw = bank.get(f"bank:machines:{machine_id}")
    if not raw: return jsonify({"error": "not found"}), 404
    return jsonify(json.loads(raw))

@app.route("/bank/history/<machine_id>")
def bank_history(machine_id):
    entries = bank.lrange(f"bank:history:{machine_id}", 0, 59)
    return jsonify({"machine_id": machine_id, "count": len(entries), "history": [json.loads(e) for e in entries]})

@app.route("/bank/alerts")
def bank_alerts():
    alerts = bank.lrange("bank:alerts", 0, 99)
    return jsonify({"count": len(alerts), "alerts": [json.loads(a) for a in alerts]})

@app.route("/bank/all")
def bank_all():
    keys = list(bank.scan_iter("bank:machines:*", count=200))
    machines = {}
    if keys:
        values = bank.mget(keys)
        for k, v in zip(keys, values):
            if v: machines[k.replace("bank:machines:","")] = json.loads(v)
    raw_s = bank.get("bank:summary")
    summary = json.loads(raw_s) if raw_s else {}
    alerts = bank.lrange("bank:alerts", 0, 19)
    return jsonify({"machines": machines, "summary": summary,
                    "recent_alerts": [json.loads(a) for a in alerts], "ts": time.time()})

@app.route("/health")
def health():
    last = r.get("digital-twin:last-update")
    age = time.time() - float(last) if last else 999
    machines = r.hgetall("digital-twin:machines")
    result = {k: json.loads(v) for k, v in machines.items()}
    critical = [k for k,v in result.items() if v["status"]=="CRITICAL"]
    warning = [k for k,v in result.items() if v["status"]=="WARNING"]
    bk = len(list(bank.scan_iter("bank:machines:*", count=200)))
    return jsonify({"status": "ok" if age < 30 else "stale", "data_age_seconds": round(age,1),
                    "machines_monitored": len(result), "bank_machines": bk,
                    "critical": len(critical), "warning": len(warning)})

threading.Thread(target=consume, daemon=True).start()
log.info("Digital Twin v3 (batched pipeline) on port 8001")
app.run(host="0.0.0.0", port=8001)
