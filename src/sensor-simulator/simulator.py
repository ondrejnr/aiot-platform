import json, time, random, math, sys
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

MQTT_HOST = "emqx.aiot.svc.cluster.local"
MQTT_PORT = 1883

# Retry connect
client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id="sensor-sim-01")
connected = False
for attempt in range(30):
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
        connected = True
        print(f"[SIM] Connected to MQTT on attempt {attempt+1}", flush=True)
        break
    except Exception as e:
        print(f"[SIM] MQTT connect attempt {attempt+1}/30 failed: {e}", flush=True)
        time.sleep(5)

if not connected:
    print("[SIM] FATAL: Cannot connect to MQTT after 30 attempts", flush=True)
    sys.exit(1)

print("[SIM] Sensor simulator started - 7 sensors, 2 factories", flush=True)

t = 0
while True:
    t += 1

    # Factory 1 - Motor area
    temp = 75.0 + 10*math.sin(t/10) + random.uniform(-2, 2)
    vibration = 0.5 + 0.3*math.sin(t/5) + random.uniform(-0.1, 0.1)
    rpm = 1450 + 200*math.sin(t/15) + random.uniform(-20, 20)
    humidity_f1 = 45 + 10*math.sin(t/20) + random.uniform(-3, 3)

    # Factory 2 - Pump area
    pressure = 100.0 + 5*math.cos(t/8) + random.uniform(-1, 1)
    humidity_f2 = 55 + 8*math.sin(t/12) + random.uniform(-2, 2)

    # Factory 3 - Energy
    energy = 120 + 30*math.sin(t/25) + random.uniform(-5, 5)
    flow = 45 + 15*math.cos(t/7) + random.uniform(-2, 2)

    sensors = [
        # Pôvodné 3 senzory
        ("sensors/factory1/temperature", {"sensor_id": "temp-001", "value": round(temp, 2), "unit": "celsius", "location": "motor-A", "machine_type": "motor"}),
        ("sensors/factory1/vibration",   {"sensor_id": "vib-001",  "value": round(max(0, vibration), 3), "unit": "mm/s", "location": "motor-A", "machine_type": "motor"}),
        ("sensors/factory2/pressure",    {"sensor_id": "pres-001", "value": round(pressure, 2), "unit": "bar", "location": "pump-B", "machine_type": "pump"}),
        # Nové senzory
        ("sensors/factory1/rpm",         {"sensor_id": "rpm-001",  "value": round(max(0, rpm), 1), "unit": "rpm", "location": "motor-A", "machine_type": "motor"}),
        ("sensors/factory1/humidity",    {"sensor_id": "hum-001",  "value": round(max(0, min(100, humidity_f1)), 1), "unit": "percent", "location": "motor-A", "machine_type": "motor"}),
        ("sensors/factory2/humidity",    {"sensor_id": "hum-002",  "value": round(max(0, min(100, humidity_f2)), 1), "unit": "percent", "location": "pump-B", "machine_type": "pump"}),
        ("sensors/factory3/energy",      {"sensor_id": "energy-001", "value": round(max(0, energy), 2), "unit": "kWh", "location": "generator-C", "machine_type": "generator"}),
        ("sensors/factory3/flow",        {"sensor_id": "flow-001",  "value": round(max(0, flow), 2), "unit": "l/min", "location": "pump-D", "machine_type": "pump"}),
    ]

    for topic, payload in sensors:
        payload["timestamp"] = time.time()
        client.publish(topic, json.dumps(payload))

    if t % 10 == 0:
        print(f"[SIM] tick={t} | sent 8 sensors | temp={temp:.1f} vib={vibration:.2f} rpm={rpm:.0f} pres={pressure:.1f} energy={energy:.1f} flow={flow:.1f}", flush=True)

    time.sleep(5)
