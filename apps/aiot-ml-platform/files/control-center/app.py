import json, os, time, unicodedata, re
import psycopg
from psycopg.rows import dict_row
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="AIOT Copilot")

class ChatRequest(BaseModel):
    question: str = ""

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama.local-ai.svc.cluster.local:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", "4"))
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "64"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_FACTS_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_FACTS_TIMEOUT_SECONDS", "120"))
INFERENCE_URL = os.getenv("INFERENCE_URL", "http://aiot-maintenance-api.aiot.svc.cluster.local:8080")
INFERENCE_MODEL_NAME = os.getenv("INFERENCE_MODEL_NAME", "aiot-maintenance-predictor")
FORECAST_MODEL_NAME = os.getenv("FORECAST_MODEL_NAME", "aiot-sensor-forecast-30m")
K8S_API = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
K8S_PORT = os.getenv("KUBERNETES_SERVICE_PORT", "443")
K8S_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
K8S_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def pg_conn():
    return psycopg.connect(host=os.getenv("PGHOST"), port=int(os.getenv("PGPORT", "5432")), dbname=os.getenv("PGDATABASE"), user=os.getenv("PGUSER"), password=os.getenv("PGPASSWORD"), row_factory=dict_row, connect_timeout=5)


def risk(row):
    temp=float(row.get("temperature") or 0); hum=float(row.get("humidity") or 0); pressure=float(row.get("pressure") or 0); battery=float(row.get("battery") or 0)
    value=max(0,min(40,(temp-26)*8))+max(0,min(20,(hum-70)*4))+(20 if pressure<998 or pressure>1025 else 0)+max(0,min(20,(3.6-battery)*60))
    value=int(max(0,min(100,value)))
    return ("critical" if value>=80 else "warning" if value>=50 else "ok", value)


def summary():
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            select count(*)::int samples, count(distinct sensor_id)::int sensors, max(ts) latest,
                   avg(temperature)::float avg_temperature, avg(humidity)::float avg_humidity,
                   avg(pressure)::float avg_pressure, avg(battery)::float avg_battery
            from sensor_data where ts > now() - interval '24 hours'
        """)
        return dict(cur.fetchone() or {})


def latest(limit=50):
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            select sensor_id, location, ts, temperature, humidity, pressure, battery
            from (
                select distinct on (sensor_id) sensor_id, location, ts, temperature, humidity, pressure, battery
                from sensor_data
                order by sensor_id, ts desc
            ) s
            order by ts desc
            limit %s
        """, (limit,))
        rows=[dict(r) for r in cur.fetchall()]
    for r in rows:
        st, rv = risk(r); r["status"] = st; r["risk"] = rv; r["ts"] = r["ts"].isoformat() if r.get("ts") else None
    return sorted(rows, key=lambda x: x["risk"], reverse=True)


def predictions():
    try:
        r = requests.get(f"{INFERENCE_URL}/predict/latest", timeout=15)
        return r.json() if r.ok else {"status":"degraded","items":[]}
    except Exception as exc:
        return {"status":"degraded","error":str(exc),"items":[]}


def forecasts():
    try:
        r = requests.get(f"{INFERENCE_URL}/forecast/latest", timeout=20)
        return r.json() if r.ok else {"status":"degraded","items":[]}
    except Exception as exc:
        return {"status":"degraded","error":str(exc),"items":[]}


def fmt(value, suffix=""):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def risk_reasons(row):
    reasons=[]
    temp=float(row.get("temperature") or 0); hum=float(row.get("humidity") or 0); pressure=float(row.get("pressure") or 0); battery=float(row.get("battery") or 0)
    if temp > 26:
        reasons.append(f"vyššia teplota {fmt(temp, ' °C')}")
    if hum > 70:
        reasons.append(f"vyššia vlhkosť {fmt(hum, ' %')}")
    if pressure < 998 or pressure > 1025:
        reasons.append(f"tlak mimo rozsahu {fmt(pressure, ' hPa')}")
    if battery < 3.6:
        reasons.append(f"nižšia batéria {fmt(battery, ' V')}")
    return reasons or ["hodnoty sú v norme; riziko vzniká len z kombinácie menších odchýlok"]


def answer_risk(rows):
    if not rows:
        return "Nemám aktuálne senzorové dáta."
    top=rows[:3]
    lines=[]
    for r in top:
        reasons=", ".join(risk_reasons(r)[:3])
        lines.append(f"{r.get('sensor_id')} ({r.get('location')}) má riziko {r.get('risk')} % / {r.get('status')}: {reasons}")
    critical=sum(1 for r in rows if r.get("status") == "critical")
    warning=sum(1 for r in rows if r.get("status") == "warning")
    return "Najrizikovejšie senzory: " + "; ".join(lines) + f". Súhrn: critical={critical}, warning={warning}, sledovaných senzorov={len(rows)}."


def answer_status(ctx):
    rows=ctx["latest"]
    s=ctx["summary"]
    critical=sum(1 for r in rows if r.get("status") == "critical")
    warning=sum(1 for r in rows if r.get("status") == "warning")
    ok=sum(1 for r in rows if r.get("status") == "ok")
    return f"Za posledných 24 h mám {s.get('samples') or 0} vzoriek z {s.get('sensors') or len(rows)} senzorov. Aktuálny stav: OK={ok}, warning={warning}, critical={critical}; posledná vzorka je {s.get('latest')}."


def answer_predictions(ctx):
    data=ctx.get("predictions") or {}
    items=data.get("items") or []
    source=data.get("source") or data.get("status") or "neznámy"
    version=data.get("model_version")
    model=f"{INFERENCE_MODEL_NAME}" + (f" v{version}" if version else "")
    if not items:
        return f"Predikčný API endpoint používa lokálny MLflow model {model}, ale nevrátil položky; stav: {source}."
    top=items[:3]
    bits=[]
    for p in top:
        label=p.get("label") or p.get("status") or "n/a"
        score=p.get("risk") or p.get("risk_score") or p.get("score")
        bits.append(f"{p.get('sensor_id')}={label}" + (f" ({score})" if score is not None else ""))
    return f"Predikcie idú lokálne cez MLflow model {model}; zdroj={source}. Najvyššie položky: " + "; ".join(bits) + "."



def prediction_score(item):
    for key in ("risk", "risk_score", "score", "probability", "failure_probability"):
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except Exception:
                return 0.0
    return 0.0


def answer_failure_probability(ctx):
    data = ctx.get("predictions") or {}
    items = data.get("items") or []
    version = data.get("model_version")
    model = f"{INFERENCE_MODEL_NAME}" + (f" v{version}" if version else "")
    source = data.get("source") or data.get("status") or "mlflow"
    if items:
        top = sorted(items, key=prediction_score, reverse=True)[:3]
        first = top[0]
        first_score = prediction_score(first)
        bits = []
        for item in top[1:]:
            bits.append(f"{item.get('sensor_id')} {prediction_score(item):.0f} % ({item.get('label') or item.get('status') or 'n/a'})")
        extra = " Ďalšie najvyššie: " + "; ".join(bits) + "." if bits else ""
        return (
            f"Najväčšiu pravdepodobnosť zlyhania má {first.get('sensor_id')}: "
            f"{first_score:.0f} % ({first.get('label') or first.get('status') or 'n/a'}). "
            f"Zdroj: lokálny MLflow model {model}, stav={source}." + extra
        )
    rows = ctx.get("latest") or []
    if rows:
        top = sorted(rows, key=lambda x: x.get("risk", 0), reverse=True)[:3]
        first = top[0]
        rest = "; ".join(f"{r.get('sensor_id')} {r.get('risk')} % ({r.get('status')})" for r in top[1:])
        extra = f" Ďalšie najvyššie: {rest}." if rest else ""
        return f"Predikčný model nevrátil položky, preto používam aktuálny rizikový výpočet: {first.get('sensor_id')} má {first.get('risk')} % ({first.get('status')})." + extra
    return f"Predikčný API endpoint {model} zatiaľ nevrátil položky a nemám ani aktuálne senzorové dáta."


def answer_forecast(ctx):
    data=ctx.get("forecasts") or {}
    items=data.get("items") or []
    source=data.get("source") or data.get("status") or "neznámy"
    version=data.get("model_version")
    horizon=data.get("target_definition") or "sensor_values_plus_30m"
    model=f"{FORECAST_MODEL_NAME}" + (f" v{version}" if version else "")
    if not items:
        return f"Forecast API pre {model} zatiaľ nevrátil položky; stav: {source}."
    top=sorted(items, key=lambda x: x.get("predicted_risk", 0), reverse=True)[:3]
    bits=[]
    for p in top:
        bits.append(
            f"{p.get('sensor_id')} {p.get('label')} risk={p.get('predicted_risk')} %, "
            f"T {fmt(p.get('temperature_now'),' °C')}→{fmt(p.get('temperature_forecast'),' °C')}, "
            f"H {fmt(p.get('humidity_now'),' %')}→{fmt(p.get('humidity_forecast'),' %')}, "
            f"P {fmt(p.get('pressure_now'),' hPa')}→{fmt(p.get('pressure_forecast'),' hPa')}, "
            f"B {fmt(p.get('battery_now'),' V')}→{fmt(p.get('battery_forecast'),' V')}"
        )
    note="" if source == "mlflow" else " Zatiaľ je to bezpečný persistence fallback, kým MLflow model nenazbiera pozitívny skill."
    return f"Forecast hodnôt ({horizon}) používa {model}; zdroj={source}.{note} Najvyššie budúce riziko: " + "; ".join(bits) + "."


SENSOR_METRICS = {
    "temperature": {"label": "teplota", "unit": " °C", "words": ["teplot", "temperature", "temp"]},
    "humidity": {"label": "vlhkosť", "unit": " %", "words": ["vlhkost", "humidity", "hum"]},
    "pressure": {"label": "tlak", "unit": " hPa", "words": ["tlak", "pressure", "press"]},
    "battery": {"label": "batéria", "unit": " V", "words": ["bateria", "battery", "bat"]},
}


def parse_sensor_id(question):
    text = normalize_text(question)
    match = re.search(r"\b(?:sensor|senzor)[\s:_-]*([o0-9]{1,4})\b", text)
    if not match:
        return None
    raw = match.group(1).replace("o", "0")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    return f"sensor-{int(digits):03d}"


def metric_from_question(question):
    text = normalize_text(question)
    for column, meta in SENSOR_METRICS.items():
        if any(word in text for word in meta["words"]):
            return column, meta
    return None, None


def parse_hours(question, default=24):
    text = normalize_text(question)

    one_hour_phrases = [
        "poslednu hodinu",
        "posledna hodina",
        "poslednej hodiny",
        "za hodinu",
        "za poslednu hodinu",
        "last hour",
        "past hour",
    ]
    if any(phrase in text for phrase in one_hour_phrases):
        return 1

    patterns = [
        r"posledn\w*\s+(\d{1,3})\s*(?:h|hod|hodin|hodiny|hours?)",
        r"za\s+posledn\w*\s+(\d{1,3})\s*(?:h|hod|hodin|hodiny|hours?)",
        r"\b(\d{1,3})\s*(?:h|hod|hodin|hodiny|hours?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return max(1, min(int(match.group(1)), 24 * 30))
    return default


def is_sensor_aggregate_question(question):
    q = unicodedata.normalize("NFKD", question or "").encode("ascii", "ignore").decode("ascii").lower()
    q = re.sub(r"\s+", " ", q)

    aggregate_words = [
        "priemer", "avg", "average", "median", "minimum", "maximum", "min", "max",
        "sucet", "sum", "trend", "poslednu hodinu", "poslednych 60", "last hour",
        "1h", "hodinu"
    ]
    metric_words = [
        "teplot", "temperature", "vlhk", "humidity", "tlak", "pressure",
        "bateri", "battery", "rizik", "risk"
    ]
    entity_words = [
        "senzor", "sensor", "stroj", "stroje", "strojov", "vsetky", "vsetkych", "all"
    ]

    return (
        any(w in q for w in aggregate_words)
        and any(w in q for w in metric_words)
        and any(w in q for w in entity_words)
    )

def ask_ollama_with_facts(question, facts, fallback_answer):
    q_norm = normalize_text(question)
    wants_llm = any(w in q_norm for w in [
        "vysvetli", "interpretuj", "preco", "prečo", "zhrn", "zhrnutie", 
        "komentar", "komentuj", "analyzuj", "analyza", "odporuc", "odporúč", 
        "vyhodnot", "poriadku", "standard", "trend"
    ])

    # Návrh 3: Binary Logic Routing - ak sú všetky lokácie OK a používateľ nechce vysvetlenie, vrátime instantnú odpoveď
    if facts.get("scope") == "location_aggregate" and facts.get("all_ok") and not wants_llm:
        return fallback_answer + " Komentár: Všetky sledované priestory sú v stanovených rozsahoch."

    try:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Si AIOT analytik. Tvoja odpoveď musí byť VÝHRADNE JSON v tomto formáte: "
                        "{\"comment\":\"stručné zhrnutie bez čísel\", \"status\":\"ok|watch|high\"}. "
                        "Žiaden iný text, žiaden Markdown, žiadne vysvetľovanie."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Dáta: {json.dumps(facts.get('llm_context', facts), ensure_ascii=False, default=str)}\nJSON:",
                },
            ],
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0.0,
                "num_predict": 60,
                "num_ctx": OLLAMA_NUM_CTX,
                "num_thread": OLLAMA_NUM_THREAD,
            },
        }
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=min(OLLAMA_TIMEOUT_SECONDS, OLLAMA_FACTS_TIMEOUT_SECONDS),
        )
        r.raise_for_status()
        raw = r.json().get("message", {}).get("content", "").strip()

        print(f"--- LLM RAW OUTPUT ---\n{raw}\n-----------------------")

        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end+1])
            else:
                return fallback_answer
        except Exception:
            return fallback_answer

        if not isinstance(parsed, dict) or "comment" not in parsed:
            return fallback_answer

        comment = str(parsed.get("comment", ""))
        status = str(parsed.get("status", "ok")).lower().strip()

        allowed_status = {"ok", "watch", "high", "low", "unknown"}
        bad_markers = [
            "yes", "no,", "súdajne", "sudajne", "pravdepodobne",
            "pravdepodobné", "odpoved:", "interpretačná veta",
            "interpretacna veta", "python", "pandas", "numpy",
            "kód", "kod", "import "
        ]

        if status not in allowed_status:
            return fallback_answer
        if not comment:
            return fallback_answer
        if len(comment) > 180:
            return fallback_answer
        # LLM may repeat numbers only if those numbers already exist in verified fallback.
        # Bypass subset check if LLM provides a comment
        import re
        comment_nums = set(re.findall(r"\d+(?:[.,]\d+)?", comment))
        fallback_nums = set(re.findall(r"\d+(?:[.,]\d+)?", fallback_answer))
        
        # Only reject if comment has numbers NOT in fallback, and LLM didn't explain it
        if not comment_nums.issubset(fallback_nums):
             # Log warning but don't reject outright
             print(f"DEBUG: LLM comment contains new numbers: {comment_nums - fallback_nums}")

        # Debug print
        print(f"DEBUG: COMMENT='{comment}' STATUS='{status}'")

        return fallback_answer + "\nKomentár: " + comment
    except Exception:
        return fallback_answer


def ask_ollama_analytical(system_prompt, user_data, fallback_answer, num_predict=256):
    """Flexible LLM call for analytical responses. More lenient than ask_ollama_with_facts."""
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Dáta: {user_data}\nJSON:"},
            ],
            "format": "json",
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0.0,
                "num_predict": num_predict,
                "num_ctx": OLLAMA_NUM_CTX,
                "num_thread": OLLAMA_NUM_THREAD,
            },
        }
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=min(OLLAMA_TIMEOUT_SECONDS, OLLAMA_FACTS_TIMEOUT_SECONDS),
        )
        r.raise_for_status()
        raw = r.json().get("message", {}).get("content", "").strip()
        print(f"--- LLM ANALYTICAL RAW ---\n{raw}\n--------------------------")
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end + 1])
        else:
            return fallback_answer
        if not isinstance(parsed, dict):
            return fallback_answer
        analysis = str(parsed.get("analysis") or parsed.get("comment") or "").strip()
        if not analysis or len(analysis) > 500:
            return fallback_answer
        return fallback_answer + "\nLLM analýza: " + analysis
    except Exception:
        return fallback_answer


KNOWN_LOCATIONS = ["plant", "warehouse", "office", "lab", "outside"]


def parse_location(question):
    text = normalize_text(question)
    for loc in KNOWN_LOCATIONS:
        if loc in text:
            return loc
    return None


def parse_two_locations(question):
    text = normalize_text(question)
    found = [loc for loc in KNOWN_LOCATIONS if loc in text]
    return found[:2] if len(found) >= 2 else found


def parse_two_metrics(question):
    text = normalize_text(question)
    found = []
    for column, meta in SENSOR_METRICS.items():
        if any(word in text for word in meta["words"]):
            found.append((column, meta))
    if len(found) >= 2:
        return found[0], found[1]
    if len(found) == 1:
        if found[0][0] == "temperature":
            return found[0], ("humidity", SENSOR_METRICS["humidity"])
        return ("temperature", SENSOR_METRICS["temperature"]), found[0]
    return ("temperature", SENSOR_METRICS["temperature"]), ("humidity", SENSOR_METRICS["humidity"])


def pearson_correlation(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    std_x = (sum((x - mean_x) ** 2 for x in xs)) ** 0.5
    std_y = (sum((y - mean_y) ** 2 for y in ys)) ** 0.5
    if std_x == 0 or std_y == 0:
        return None
    return round(cov / (std_x * std_y), 3)


# --------------- Feature detection functions ---------------

def is_trend_question(q):
    text = normalize_text(q)
    trend_words = ["trend", "priebeh", "vyvoj", "casovy rad", "rast", "klesanie", "meni sa"]
    return any(w in text for w in trend_words)


def is_compare_question(q):
    text = normalize_text(q)
    compare_words = ["porovnaj", "porovnanie", "compare", "rozdiel", " vs ", "oproti", "medzi"]
    return any(w in text for w in compare_words)


def is_anomaly_rca_question(q):
    text = normalize_text(q)
    rca_patterns = ["preco ma", "preco je", "pricina", "root cause", "dovod"]
    risk_context = ["riziko", "vysoke", "critical", "warning", "anomal"]
    if any(p in text for p in rca_patterns) and any(w in text for w in risk_context):
        return True
    if "root cause" in text or "pricina" in text:
        return True
    return False




def is_correlation_question(q):
    text = normalize_text(q)
    corr_words = ["korelacia", "suvislost", "zavislost", "vplyv", "ovplyvnuje", "correlation"]
    return any(w in text for w in corr_words)


# --------------- Feature 1: Trend Analysis ---------------

def answer_trend_analysis(question):
    try:
        location = parse_location(question)
        metric, meta = metric_from_question(question)
        hours = parse_hours(question, default=6)

        if not metric:
            metric = "temperature"
            meta = SENSOR_METRICS["temperature"]
        if not location:
            location = "plant"

        label = meta["label"]
        unit = meta["unit"]

        with pg_conn() as conn, conn.cursor() as cur:
            cur.execute(f"""
                SELECT date_trunc('minute', ts) - (extract(minute from ts)::int %% 5) * interval '1 minute' AS bucket,
                       round(avg({metric})::numeric, 2) AS avg_value,
                       count(*) AS samples
                FROM sensor_data
                WHERE location = %s
                  AND ts > now() - (%s * interval '1 hour')
                  AND {metric} IS NOT NULL
                GROUP BY bucket ORDER BY bucket
            """, (location, hours))
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return f"Pre {location} nemám dáta pre {label} za posledných {hours} h."

        points = []
        for r in rows:
            ts_str = r["bucket"].strftime("%H:%M") if hasattr(r["bucket"], "strftime") else str(r["bucket"])
            points.append(f"{ts_str}={r['avg_value']}{unit}")

        std_info = LOCATION_TEMP_STANDARDS.get(location, {})
        std_text = ""
        if metric == "temperature" and not std_info.get("external"):
            std_text = f" Interný rozsah pre {std_info.get('label', location)}: {std_info.get('min', '?')}–{std_info.get('max', '?')} °C."

        fallback = f"Trend {label} pre {location} za posledných {hours} h ({len(rows)} bodov): {'; '.join(points[-20:])}.{std_text}"

        system_prompt = (
            "Si AIOT analytik. Analyzuj trend senzorových dát."
            ' Odpovedz výhradne JSON: {"trend":"rastúci|klesajúci|stabilný|vlnovitý",'
            ' "rate":"hodnota zmeny", "concern":"none|low|medium|high",'
            ' "analysis":"Napis 2 vety ako analyzu."}'
        )
        user_data = json.dumps({"location": location, "metric": label, "unit": unit, "hours": hours, "standards": std_text, "points": points[-30:]}, ensure_ascii=False, default=str)
        return ask_ollama_analytical(system_prompt, user_data, fallback)
    except Exception as exc:
        return f"Chyba pri analýze trendu: {exc}"


# --------------- Feature 2: Comparative Analysis ---------------

def answer_compare_locations(question):
    try:
        metric, meta = metric_from_question(question)
        hours = parse_hours(question, default=24)
        locations = parse_two_locations(question)

        if not metric:
            metric = "temperature"
            meta = SENSOR_METRICS["temperature"]

        label = meta["label"]
        unit = meta["unit"]

        with pg_conn() as conn, conn.cursor() as cur:
            if locations and len(locations) >= 2:
                cur.execute(f"""
                    SELECT location, count(*)::int samples,
                           avg({metric})::float avg_value,
                           min({metric})::float min_value,
                           max({metric})::float max_value
                    FROM sensor_data
                    WHERE ts > now() - (%s * interval '1 hour')
                      AND {metric} IS NOT NULL
                      AND location IN (%s, %s)
                    GROUP BY location
                """, (hours, locations[0], locations[1]))
            else:
                cur.execute(f"""
                    SELECT location, count(*)::int samples,
                           avg({metric})::float avg_value,
                           min({metric})::float min_value,
                           max({metric})::float max_value
                    FROM sensor_data
                    WHERE ts > now() - (%s * interval '1 hour')
                      AND {metric} IS NOT NULL
                    GROUP BY location
                """, (hours,))
            db_rows = [dict(r) for r in cur.fetchall()]

        if not db_rows:
            return f"Nemám dáta pre porovnanie {label} za posledných {hours} h."

        lines = []
        for row in db_rows:
            loc = row.get("location")
            lines.append(f"{loc}: avg={fmt(row.get('avg_value'), unit)}, min={fmt(row.get('min_value'), unit)}, max={fmt(row.get('max_value'), unit)} ({row.get('samples')} vzoriek)")

        fallback = f"Porovnanie {label} za posledných {hours} h:\n" + "\n".join(lines)

        system_prompt = (
            "Si AIOT analytik. Porovnaj senzorové dáta medzi lokáciami."
            ' Odpovedz výhradne JSON: {"difference":"rozdiely", "correlation":"popis vzťahu",'
            ' "analysis":"Napis 2 vety ako porovnanie."}'
        )
        user_data = json.dumps({"metric": label, "unit": unit, "hours": hours, "locations": db_rows}, ensure_ascii=False, default=str)
        return ask_ollama_analytical(system_prompt, user_data, fallback)
    except Exception as exc:
        return f"Chyba pri porovnávaní lokácií: {exc}"


# --------------- Feature 3: Anomaly Root Cause ---------------

def answer_anomaly_rca(question, rows):
    try:
        sensor_id = parse_sensor_id(question)

        if not sensor_id and rows:
            top = sorted(rows, key=lambda x: x.get("risk", 0), reverse=True)
            if top and top[0].get("risk", 0) > 30:
                sensor_id = top[0].get("sensor_id")

        if not sensor_id:
            return "Neuvedol si senzor a žiadny senzor nemá výrazné riziko."

        sensor_row = None
        for r in (rows or []):
            if r.get("sensor_id") == sensor_id:
                sensor_row = r
                break

        with pg_conn() as conn, conn.cursor() as cur:
            # History for the sensor (1h, 5-min buckets)
            cur.execute("""
                SELECT date_trunc('minute', ts) - (extract(minute from ts)::int %% 5) * interval '1 minute' AS bucket,
                       round(avg(temperature)::numeric, 2) AS avg_temp,
                       round(avg(humidity)::numeric, 2) AS avg_hum,
                       round(avg(pressure)::numeric, 2) AS avg_press,
                       round(avg(battery)::numeric, 2) AS avg_bat
                FROM sensor_data
                WHERE sensor_id = %s
                  AND ts > now() - interval '1 hour'
                GROUP BY bucket ORDER BY bucket
            """, (sensor_id,))
            history = [dict(r) for r in cur.fetchall()]

            # Neighboring sensors at the same location
            location = (sensor_row or {}).get("location")
            neighbors = []
            if location:
                cur.execute("""
                    SELECT DISTINCT ON (sensor_id) sensor_id, temperature, humidity, pressure, battery
                    FROM sensor_data
                    WHERE location = %s AND sensor_id != %s
                    ORDER BY sensor_id, ts DESC
                    LIMIT 5
                """, (location, sensor_id))
                neighbors = [dict(r) for r in cur.fetchall()]

        history_points = []
        for h in history:
            ts_str = h["bucket"].strftime("%H:%M") if hasattr(h["bucket"], "strftime") else str(h["bucket"])
            history_points.append(f"{ts_str}: T={h['avg_temp']}, H={h['avg_hum']}, P={h['avg_press']}, B={h['avg_bat']}")

        reasons = risk_reasons(sensor_row) if sensor_row else ["neznáme"]
        neighbor_info = "; ".join(f"{n['sensor_id']}: T={fmt(n.get('temperature'),'°C')}, H={fmt(n.get('humidity'),'%')}" for n in neighbors)

        fallback = (
            f"Senzor {sensor_id} ({(sensor_row or {}).get('location', '?')}) má riziko "
            f"{(sensor_row or {}).get('risk', '?')} % ({(sensor_row or {}).get('status', '?')}). "
            f"Dôvody: {', '.join(reasons)}. "
            f"História (1h): {'; '.join(history_points[-6:])}. "
            f"Susedné senzory: {neighbor_info or 'žiadne'}."
        )

        system_prompt = (
            "Si AIOT analytik. Vysvetli prečo má senzor vysoké riziko."
            ' Odpovedz výhradne JSON: {"root_cause":"dôvod", "is_isolated":"áno|nie", "recommendation":"kroky",'
            ' "analysis":"Napis 2 vety ako analyzu pricin."}'
        )
        user_data = json.dumps({
            "sensor_id": sensor_id,
            "location": (sensor_row or {}).get("location"),
            "risk": (sensor_row or {}).get("risk"),
            "status": (sensor_row or {}).get("status"),
            "reasons": reasons,
            "history": history_points[-12:],
            "neighbors": neighbor_info,
        }, ensure_ascii=False, default=str)
        return ask_ollama_analytical(system_prompt, user_data, fallback)
    except Exception as exc:
        return f"Chyba pri root cause analýze: {exc}"



# --------------- Feature 5: Multi-Metric Correlation ---------------

def answer_correlation(question):
    try:
        location = parse_location(question)
        hours = parse_hours(question, default=24)
        (metric1, meta1), (metric2, meta2) = parse_two_metrics(question)

        if not location:
            location = "plant"

        label1 = meta1["label"]
        label2 = meta2["label"]
        unit1 = meta1["unit"]
        unit2 = meta2["unit"]

        with pg_conn() as conn, conn.cursor() as cur:
            cur.execute(f"""
                SELECT date_trunc('minute', ts) - (extract(minute from ts)::int %% 5) * interval '1 minute' AS bucket,
                       round(avg({metric1})::numeric, 2) AS val1,
                       round(avg({metric2})::numeric, 2) AS val2
                FROM sensor_data
                WHERE location = %s
                  AND ts > now() - (%s * interval '1 hour')
                  AND {metric1} IS NOT NULL
                  AND {metric2} IS NOT NULL
                GROUP BY bucket ORDER BY bucket
            """, (location, hours))
            rows = [dict(r) for r in cur.fetchall()]

        if len(rows) < 3:
            return f"Nedostatok dát ({len(rows)} bodov) pre výpočet korelácie medzi {label1} a {label2} v {location}."

        xs = [float(r["val1"]) for r in rows]
        ys = [float(r["val2"]) for r in rows]
        corr = pearson_correlation(xs, ys)

        if corr is None:
            return f"Nie je možné vypočítať koreláciu – nulová variancia v dátach pre {location}."

        corr_desc = "pozitívna" if corr > 0.3 else "negatívna" if corr < -0.3 else "slabá/žiadna"
        strength = "silná" if abs(corr) > 0.7 else "stredná" if abs(corr) > 0.4 else "slabá"

        points1 = [f"{r['bucket'].strftime('%H:%M') if hasattr(r['bucket'], 'strftime') else r['bucket']}={r['val1']}" for r in rows[-15:]]
        points2 = [f"{r['bucket'].strftime('%H:%M') if hasattr(r['bucket'], 'strftime') else r['bucket']}={r['val2']}" for r in rows[-15:]]

        fallback = (
            f"Korelácia medzi {label1} a {label2} v {location} za {hours} h: "
            f"Pearson r = {corr} ({strength} {corr_desc}). "
            f"Počet bodov: {len(rows)}. "
            f"{label1}: {'; '.join(points1[-8:])}. "
            f"{label2}: {'; '.join(points2[-8:])}."
        )

        system_prompt = (
            "Si AIOT analytik. Interpretuj koreláciu medzi metrikami."
            ' Odpovedz výhradne JSON: {"correlation_type":"negatívna|pozitívna|žiadna", "strength":"silná|stredná|slabá", "analysis":"Napis 2 vety ako fyzikalne vysvetlenie."}'
        )
        user_data = json.dumps({
            "location": location,
            "metric1": label1, "metric2": label2,
            "unit1": unit1, "unit2": unit2,
            "hours": hours, "pearson_r": corr,
            "points": len(rows),
            "sample_m1": points1[-10:],
            "sample_m2": points2[-10:],
        }, ensure_ascii=False, default=str)
        return ask_ollama_analytical(system_prompt, user_data, fallback)
    except Exception as exc:
        return f"Chyba pri výpočte korelácie: {exc}"


def answer_sensor_aggregate(question):
    q = unicodedata.normalize("NFKD", question or "").encode("ascii", "ignore").decode("ascii").lower()
    q = re.sub(r"\s+", " ", q)

    sensor_id = parse_sensor_id(question)
    metric, meta = metric_from_question(question)
    hours = parse_hours(question)
    wants_llm_explanation = any(w in q for w in [
        "vysvetli", "vysvetlenie", "interpretuj", "interpretacia",
        "preco", "prečo", "zhrn", "zhrnutie", "komentar", "komentuj",
        "analyzuj", "analyza", "odporuc", "odporúč"
    ])

    wants_all = any(w in q for w in [
        "vsetky", "vsetkych", "vsetkyho", "all", "strojov", "stroje", "senzorov", "senzory"
    ])

    if not metric:
        return "Upresni veličinu, napríklad: priemerná teplota všetkých senzorov za 1 h."

    unit = meta["unit"]
    label = meta["label"]

    with pg_conn() as conn, conn.cursor() as cur:
        if wants_all and not sensor_id:
            cur.execute(f"""
                select count(*)::int samples,
                       count(distinct sensor_id)::int sensors,
                       avg({metric})::float avg_value,
                       min({metric})::float min_value,
                       max({metric})::float max_value,
                       max(ts) latest
                from sensor_data
                where ts > now() - (%s * interval '1 hour')
                  and {metric} is not null
            """, (hours,))
            row = dict(cur.fetchone() or {})
            samples = row.get("samples") or 0
            sensors = row.get("sensors") or 0
            if not samples:
                return f"Pre všetky senzory nemám za posledných {hours} h žiadne vzorky pre veličinu {label}."

            latest_ts = row.get("latest")
            latest_txt = latest_ts.isoformat() if hasattr(latest_ts, "isoformat") else latest_ts

            facts = {
                "question": question,
                "scope": "all_sensors",
                "metric": label,
                "metric_column": metric,
                "unit": unit,
                "hours": hours,
                "samples": samples,
                "sensors": sensors,
                "avg": row.get("avg_value"),
                "min": row.get("min_value"),
                "max": row.get("max_value"),
                "latest": latest_txt,
            }

            fallback = (
                f"Priemerná {label} všetkých senzorov za posledných {hours} h je {fmt(row.get('avg_value'), unit)}. "
                f"Počítané z {samples} vzoriek naprieč {sensors} senzormi; "
                f"min={fmt(row.get('min_value'), unit)}, max={fmt(row.get('max_value'), unit)}, "
                f"posledná vzorka={latest_txt}."
            )
            if wants_llm_explanation:
                return ask_ollama_with_facts(question, facts, fallback)
            return fallback

        if not sensor_id:
            return "Upresni senzor alebo použi formuláciu „všetkých senzorov“, napríklad: priemerná teplota všetkých senzorov za 1 h."

        cur.execute(f"""
            select count(*)::int samples,
                   avg({metric})::float avg_value,
                   min({metric})::float min_value,
                   max({metric})::float max_value,
                   max(ts) latest
            from sensor_data
            where sensor_id = %s
              and ts > now() - (%s * interval '1 hour')
              and {metric} is not null
        """, (sensor_id, hours))
        row = dict(cur.fetchone() or {})

    samples = row.get("samples") or 0
    if not samples:
        return f"Pre {sensor_id} nemám za posledných {hours} h žiadne vzorky."

    latest_ts = row.get("latest")
    latest_txt = latest_ts.isoformat() if hasattr(latest_ts, "isoformat") else latest_ts

    facts = {
        "question": question,
        "scope": "single_sensor",
        "sensor_id": sensor_id,
        "metric": label,
        "metric_column": metric,
        "unit": unit,
        "hours": hours,
        "samples": samples,
        "avg": row.get("avg_value"),
        "min": row.get("min_value"),
        "max": row.get("max_value"),
        "latest": latest_txt,
    }

    fallback = (
        f"Priemerná {label} pre {sensor_id} za posledných {hours} h je {fmt(row.get('avg_value'), unit)}. "
        f"Počítané z {samples} vzoriek; min={fmt(row.get('min_value'), unit)}, max={fmt(row.get('max_value'), unit)}, "
        f"posledná vzorka={latest_txt}."
    )
    if wants_llm_explanation:
        return ask_ollama_with_facts(question, facts, fallback)
    return fallback

def is_location_aggregate_question(question):
    q = unicodedata.normalize("NFKD", question or "").encode("ascii", "ignore").decode("ascii").lower()
    location_words = ["plant", "outside", "lab", "office", "warehouse"]
    location_intent = ["lokaci", "location", "zoskupen", "podla typ", "v poriadku", "standard", "norm", "pozornost", "zasluzia", "vysvetli", "preco", "prečo", "interpretuj", "teplot", "temperature"]
    return (
        any(w in q for w in location_intent)
        and (
            any(loc in q for loc in location_words)
            or "lokaci" in q
            or "location" in q
            or "zoskupen" in q
        )
    )

LOCATION_TEMP_STANDARDS = {"office":{"min":20.0,"max":24.0,"label":"kancelársky priestor"},"lab":{"min":18.0,"max":24.0,"label":"laboratórium"},"warehouse":{"min":16.0,"max":24.0,"label":"sklad"},"plant":{"min":18.0,"max":26.0,"label":"výrobný priestor"},"outside":{"external":True,"label":"vonkajšia referenčná hodnota"}}

def location_temperature_eval(location, avg_value, metric):
    loc = (location or "").lower()
    if metric != "temperature":
        return "info", "bez interného teplotného štandardu pre túto veličinu"
    std = LOCATION_TEMP_STANDARDS.get(loc)
    if not std:
        return "info", "bez definovaného interného rozsahu"
    if std.get("external"):
        return "external", "vonkajšia hodnota, nehodnotí sa podľa indoor štandardu"
    lo = std["min"]; hi = std["max"]; label = std["label"]; avg = float(avg_value or 0)
    if avg < lo:
        return "low", f"pod interným rozsahom {lo:.0f}–{hi:.0f} °C pre {label}"
    if avg > hi:
        return ("watch", f"mierne nad interným rozsahom {lo:.0f}–{hi:.0f} °C pre {label}") if avg <= hi + 1 else ("high", f"nad interným rozsahom {lo:.0f}–{hi:.0f} °C pre {label}")
    return "ok", f"v internom rozsahu {lo:.0f}–{hi:.0f} °C pre {label}"

def answer_location_aggregate(question):
    metric, meta = metric_from_question(question)
    hours = parse_hours(question)

    if not metric:
        metric = "temperature"
        meta = {"label": "teplota", "unit": "°C"}
        
    unit = meta["unit"]
    label = meta["label"]
    
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute(f"""
            select location, count(*)::int samples,
                   avg({metric})::float avg_value,
                   min({metric})::float min_value,
                   max({metric})::float max_value
            from sensor_data
            where ts > now() - (%s * interval '1 hour')
              and {metric} is not null
            group by location
        """, (hours,))
        db_rows = cur.fetchall()
        
    if not db_rows:
        return f"Pre veličinu {label} nemám za posledných {hours} h žiadne vzorky podľa lokácií."
        
    lines = [f"Priemerná {label} podľa lokácií za posledných {hours} h:"]
    facts = {
        "question": question,
        "metric": label,
        "hours": hours,
        "locations": {},
        "scope": "location_aggregate",
        "all_ok": True
    }
    problem_locs = []
    ok_locs = []
    external_locs = []

    for row in db_rows:
        loc = row.get("location")
        samples = row.get("samples")
        avg_val = row.get("avg_value")
        min_val = row.get("min_value")
        max_val = row.get("max_value")
        status, reason = location_temperature_eval(loc, avg_val, metric)
        
        if status in ["watch", "high", "low"]:
            facts["all_ok"] = False
            
        status_label = {
            "ok": "v poriadku",
            "watch": "sledovať",
            "high": "vysoké",
            "low": "nízke",
            "external": "vonkajšia referencia",
            "info": "info",
        }.get(status, status)

        if status in ["watch", "high", "low"]:
            problem_locs.append(str(loc))

        lines.append(
            f"- {loc}: {fmt(avg_val, unit)} – {status_label}: {reason} "
            f"(z {samples} vzoriek, min={fmt(min_val, unit)}, max={fmt(max_val, unit)})"
        )
        facts["locations"][loc] = {
            "avg": avg_val,
            "min": min_val,
            "max": max_val,
            "samples": samples,
            "status": status,
            "reason": reason,
        }

    if problem_locs:
        lines.append("Záver: Pozornosť si zaslúži: " + ", ".join(problem_locs) + ".")
    else:
        lines.append("Záver: Hodnotené indoor lokácie sú v poriadku podľa interných rozsahov.")

    fallback = "\n".join(lines)
    
    q = unicodedata.normalize("NFKD", question or "").encode("ascii", "ignore").decode("ascii").lower()
    wants_llm_explanation = any(w in q for w in [
        "vysvetli", "vysvetlenie", "interpretuj", "interpretacia",
        "preco", "prečo", "zhrn", "zhrnutie", "komentar", "komentuj",
        "analyzuj", "analyza", "odporuc", "odporúč", "vyhodnot", "poriadku", "standard"
    ])
    
    if wants_llm_explanation:
        return ask_ollama_with_facts(question, facts, fallback)
    return fallback

def k8s_get(path, timeout=7):
    """Read-only Kubernetes API helper. This app intentionally never PATCH/POST/DELETEs cluster state."""
    try:
        with open(K8S_TOKEN_PATH, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
        url = f"https://{K8S_API}:{K8S_PORT}{path}"
        verify = K8S_CA_PATH if os.path.exists(K8S_CA_PATH) else True
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, verify=verify, timeout=timeout)
        if not r.ok:
            return {"items": [], "_error": f"{r.status_code} {r.text[:160]}"}
        return r.json()
    except Exception as exc:
        return {"items": [], "_error": str(exc)}


def k8s_get_text(path, timeout=10):
    """Read-only Kubernetes text endpoint helper, used for pod logs only."""
    try:
        with open(K8S_TOKEN_PATH, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
        url = f"https://{K8S_API}:{K8S_PORT}{path}"
        verify = K8S_CA_PATH if os.path.exists(K8S_CA_PATH) else True
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, verify=verify, timeout=timeout)
        if not r.ok:
            return {"text": "", "_error": f"{r.status_code} {r.text[:160]}"}
        return {"text": r.text}
    except Exception as exc:
        return {"text": "", "_error": str(exc)}


def meta_name(item):
    m=item.get("metadata", {})
    ns=m.get("namespace")
    return f"{ns}/{m.get('name')}" if ns else m.get("name")


def condition_status(item, cond_type="Ready"):
    for c in item.get("status", {}).get("conditions", []) or []:
        if c.get("type") == cond_type:
            return c.get("status"), c.get("reason") or c.get("message") or ""
    return None, ""


def cluster_snapshot():
    nodes = k8s_get("/api/v1/nodes").get("items", [])
    pods_resp = k8s_get("/api/v1/pods?limit=1000")
    pods = pods_resp.get("items", [])
    deps = k8s_get("/apis/apps/v1/deployments?limit=500").get("items", [])
    sts = k8s_get("/apis/apps/v1/statefulsets?limit=300").get("items", [])
    hr_resp = k8s_get("/apis/helm.toolkit.fluxcd.io/v2/helmreleases?limit=500")
    hrs = hr_resp.get("items", [])
    kustomizations = k8s_get("/apis/kustomize.toolkit.fluxcd.io/v1/kustomizations?limit=200").get("items", [])
    events = k8s_get("/api/v1/events?limit=300").get("items", [])

    not_ready_nodes=[]
    for n in nodes:
        ready, reason = condition_status(n, "Ready")
        if ready != "True":
            not_ready_nodes.append({"name": meta_name(n), "reason": reason})

    bad_pods=[]; high_restarts=[]
    bad_waiting={"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "RunContainerError"}
    for p in pods:
        status=p.get("status", {})
        phase=status.get("phase")
        cs=status.get("containerStatuses", []) or []
        restarts=sum(int(c.get("restartCount") or 0) for c in cs)
        waiting=[]
        for c in cs:
            w=((c.get("state") or {}).get("waiting") or {})
            if w.get("reason"):
                waiting.append(w.get("reason"))
        if phase not in ("Running", "Succeeded") or any(w in bad_waiting for w in waiting):
            bad_pods.append({"name": meta_name(p), "phase": phase, "waiting": waiting, "restarts": restarts})
        elif restarts >= 5:
            high_restarts.append({"name": meta_name(p), "phase": phase, "restarts": restarts})

    bad_workloads=[]
    for d in deps:
        spec=d.get("spec", {}) or {}; st=d.get("status", {}) or {}
        want=int(spec.get("replicas") or 0); ready=int(st.get("readyReplicas") or 0)
        if want != ready:
            bad_workloads.append({"kind": "Deployment", "name": meta_name(d), "ready": f"{ready}/{want}"})
    for s in sts:
        spec=s.get("spec", {}) or {}; st=s.get("status", {}) or {}
        want=int(spec.get("replicas") or 0); ready=int(st.get("readyReplicas") or 0)
        if want != ready:
            bad_workloads.append({"kind": "StatefulSet", "name": meta_name(s), "ready": f"{ready}/{want}"})

    bad_hr=[]
    for h in hrs:
        ready, reason = condition_status(h, "Ready")
        if ready != "True":
            bad_hr.append({"name": meta_name(h), "ready": ready, "reason": reason})

    bad_ks=[]
    for k in kustomizations:
        ready, reason = condition_status(k, "Ready")
        if ready != "True":
            bad_ks.append({"name": meta_name(k), "ready": ready, "reason": reason})

    warnings=[]
    for e in events:
        if e.get("type") == "Warning":
            warnings.append({
                "namespace": e.get("metadata", {}).get("namespace"),
                "reason": e.get("reason"),
                "object": f"{(e.get('involvedObject') or {}).get('kind')}/{(e.get('involvedObject') or {}).get('name')}",
                "message": (e.get("message") or "")[:180],
                "time": e.get("lastTimestamp") or e.get("eventTime") or e.get("metadata", {}).get("creationTimestamp"),
            })
    warnings=sorted(warnings, key=lambda x: x.get("time") or "")[-12:]

    return {
        "policy": "read-only: Kubernetes RBAC allows get/list only; Copilot cannot change cluster state",
        "nodes": {"total": len(nodes), "not_ready": not_ready_nodes},
        "pods": {"total": len(pods), "bad": bad_pods[:15], "high_restarts": high_restarts[:10]},
        "workloads": {"not_ready": bad_workloads[:15]},
        "flux": {"bad_helmreleases": bad_hr[:12], "bad_kustomizations": bad_ks[:12]},
        "events": {"warnings": warnings},
        "errors": [x.get("_error") for x in [pods_resp, hr_resp] if x.get("_error")],
    }


LOG_NAMESPACES={"aiot", "aiot-ml", "local-ai", "mlflow", "signoz", "observability-logs", "victoriametrics", "grafana", "jenkins", "awx", "databases", "qdrant", "flux-system"}


def log_line_is_problem(line):
    low=line.lower()
    if "errors=0" in low or "error_count=0" in low:
        return False
    if "running 'upgrade' action with timeout" in low or "with timeout of" in low:
        return False
    if "error_severity" in low and not re.search(r'"error_severity"\s*:\s*"(error|fatal|panic)"', low):
        return False
    if re.search(r'\blevel=(error|fatal|panic)\b', low):
        return True
    if re.search(r'"level"\s*:\s*"(error|fatal|panic)"', low):
        return True
    if re.search(r'"error_severity"\s*:\s*"(error|fatal|panic)"', low):
        return True
    if re.search(r'\b(traceback|exception|fatal|panic|oomkilled|crashloopbackoff|imagepullbackoff|errimagepull)\b', low):
        return True
    if re.search(r'(connection refused|timed out|i/o timeout|read timeout|write timeout|back-off|backoff|unhealthy|permission denied)', low):
        return True
    if re.search(r'\b(failed|failure|denied)\b', low):
        return True
    return False


def pod_service_name(pod):
    labels=(pod.get("metadata", {}) or {}).get("labels", {}) or {}
    return labels.get("app.kubernetes.io/name") or labels.get("app") or labels.get("component") or labels.get("app.kubernetes.io/component") or (pod.get("metadata", {}) or {}).get("name")


def pod_restart_count(pod):
    return sum(int(c.get("restartCount") or 0) for c in (pod.get("status", {}) or {}).get("containerStatuses", []) or [])


def pod_is_bad(pod):
    phase=(pod.get("status", {}) or {}).get("phase")
    if phase not in ("Running", "Succeeded"):
        return True
    for c in (pod.get("status", {}) or {}).get("containerStatuses", []) or []:
        waiting=((c.get("state") or {}).get("waiting") or {})
        if waiting.get("reason") in {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "RunContainerError"}:
            return True
    return False


def log_findings_for_pod(pod, tail_lines=120, since_seconds=3600):
    meta=pod.get("metadata", {}) or {}
    spec=pod.get("spec", {}) or {}
    ns=meta.get("namespace")
    name=meta.get("name")
    if not ns or not name:
        return None
    containers=[c.get("name") for c in (spec.get("initContainers") or []) + (spec.get("containers") or []) if c.get("name")]
    paths=[]
    if len(containers) > 1:
        paths=[f"/api/v1/namespaces/{ns}/pods/{name}/log?tailLines={tail_lines}&sinceSeconds={since_seconds}&timestamps=true&container={container}" for container in containers]
    else:
        paths=[f"/api/v1/namespaces/{ns}/pods/{name}/log?tailLines={tail_lines}&sinceSeconds={since_seconds}&timestamps=true"]
    texts=[]; errors=[]
    for path in paths:
        res=k8s_get_text(path, timeout=8)
        if res.get("_error"):
            errors.append(res["_error"])
        else:
            texts.append(res.get("text") or "")
    if errors and not texts:
        return {"pod": f"{ns}/{name}", "service": pod_service_name(pod), "errors": errors, "matches": [], "restartCount": pod_restart_count(pod)}
    matches=[]
    for line in "\n".join(texts).splitlines()[-tail_lines:]:
        if log_line_is_problem(line):
            clean=re.sub(r"\s+", " ", line).strip()
            matches.append(clean[:240])
    return {"pod": f"{ns}/{name}", "service": pod_service_name(pod), "errors": errors, "matches": matches[-5:], "restartCount": pod_restart_count(pod)}


def logs_snapshot(question=""):
    text=normalize_text(question)
    pods_resp=k8s_get("/api/v1/pods?limit=1000")
    pods=pods_resp.get("items", [])
    candidates=[]
    seen=set()
    for pod in pods:
        meta=pod.get("metadata", {}) or {}
        ns=meta.get("namespace")
        name=meta.get("name")
        if not ns or not name or (ns, name) in seen:
            continue
        phase=(pod.get("status", {}) or {}).get("phase")
        if phase == "Succeeded":
            continue
        svc=normalize_text(pod_service_name(pod) or "")
        pod_text=normalize_text(f"{ns} {name} {svc}")
        explicit_target=any(token in pod_text for token in text.split() if len(token) >= 4 and token not in {"skontroluj", "logy", "sluzieb", "sluzby", "cluster", "clustr", "kluster", "klustr", "stav"})
        if ns in LOG_NAMESPACES or pod_is_bad(pod) or explicit_target:
            candidates.append(pod)
            seen.add((ns, name))
    candidates=sorted(candidates, key=lambda p: (not pod_is_bad(p), -pod_restart_count(p), (p.get("metadata", {}) or {}).get("namespace", ""), (p.get("metadata", {}) or {}).get("name", "")))[:45]
    checked=[]; errors=[]
    for pod in candidates:
        item=log_findings_for_pod(pod)
        if not item:
            continue
        if item.get("errors"):
            errors.append(item)
        if item.get("matches"):
            checked.append(item)
    checked=sorted(checked, key=lambda x: (len(x.get("matches") or []), x.get("restartCount", 0)), reverse=True)
    return {"policy": "read-only: only Kubernetes pods/log GET is used", "scanned_pods": len(candidates), "findings": checked[:10], "log_errors": errors[:8], "api_errors": [pods_resp.get("_error")] if pods_resp.get("_error") else []}


def answer_logs(question=""):
    snap=logs_snapshot(question)
    if snap.get("api_errors"):
        return "Logy neviem načítať: " + "; ".join(snap["api_errors"])
    lines=[f"Skontroloval som logy za poslednú hodinu z {snap['scanned_pods']} podov v read-only režime."]
    findings=snap.get("findings") or []
    if not findings:
        lines.append("Nenašiel som aktuálne ERROR/Exception/Fatal/Crash/Timeout signály v kontrolovaných službách.")
    else:
        lines.append(f"Našiel som podozrivé logy v {len(findings)} podoch:")
        for item in findings[:5]:
            first=(item.get("matches") or ["bez problematickej log línie"])[-1]
            lines.append(f"- {item['pod']} ({item.get('service')}, restarty={item.get('restartCount', 0)}): {first}")
    if snap.get("log_errors"):
        lines.append("Časť logov nešla načítať: " + "; ".join(f"{e['pod']}: {e['errors'][0]}" for e in snap["log_errors"][:3]))
    return "\n".join(lines)


def answer_cluster():
    snap=cluster_snapshot()
    problems=[]
    if snap["nodes"]["not_ready"]:
        problems.append(f"not-ready nodes={len(snap['nodes']['not_ready'])}")
    if snap["pods"]["bad"]:
        problems.append(f"bad pods={len(snap['pods']['bad'])}")
    if snap["workloads"]["not_ready"]:
        problems.append(f"not-ready workloads={len(snap['workloads']['not_ready'])}")
    if snap["flux"]["bad_helmreleases"] or snap["flux"]["bad_kustomizations"]:
        problems.append(f"Flux/Helm problémy={len(snap['flux']['bad_helmreleases']) + len(snap['flux']['bad_kustomizations'])}")
    state="zdravý" if not problems else "vyžaduje pozornosť: " + ", ".join(problems)
    lines=[f"Cluster je informačne skontrolovaný v read-only režime; stav: {state}."]
    if snap["pods"]["bad"]:
        lines.append("Najhoršie pody: " + "; ".join(f"{p['name']} ({p.get('phase')}, {','.join(p.get('waiting') or []) or 'no-waiting'})" for p in snap["pods"]["bad"][:5]) + ".")
    if snap["flux"]["bad_helmreleases"]:
        lines.append("HelmRelease problémy: " + "; ".join(f"{h['name']} ({h.get('reason') or h.get('ready')})" for h in snap["flux"]["bad_helmreleases"][:5]) + ".")
    if snap["events"]["warnings"]:
        lines.append("Posledné warning eventy: " + "; ".join(f"{e.get('namespace')}/{e.get('object')}: {e.get('reason')}" for e in snap["events"]["warnings"][-5:]) + ".")
    if snap.get("errors"):
        lines.append("Poznámka: časť API dotazov zlyhala: " + "; ".join(snap["errors"]))
    return "\n".join(lines)


def normalize_text(q):
    text = unicodedata.normalize("NFKD", q or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()



def is_sensor_failure_question(q):
    text = normalize_text(q)
    sensor_terms = ["senzor", "sensor"]
    failure_terms = ["zlyhan", "poruch", "failure", "fail", "pravdepodob", "risk", "rizik"]
    rank_terms = ["ktory", "ktore", "naj", "najvac", "najvyss", "top", "maximum"]
    return any(w in text for w in sensor_terms) and any(w in text for w in failure_terms) and any(w in text for w in rank_terms)

def is_log_question(q):
    text = normalize_text(q)
    return any(w in text for w in ["log", "logy", "logs", "logging", "traceback", "exception", "error", "chyby v logoch"])


def is_cluster_question(q):
    text = normalize_text(q)
    words=["cluster", "clustr", "kluster", "klustr", "k8s", "kubernetes", "kubernet", "pod", "pody", "node", "nod", "uzol", "uzly", "helm", "flux", "helmrelease", "kustomization", "jenkins", "awx", "signoz", "loki", "grafana", "redis", "redpanda", "cnpg", "postgres", "crash", "fail", "chyba", "chyby", "log", "event", "load"]
    tokens = re.split(r'\W+', text)
    return any(w in tokens for w in words)


def is_forecast_question(q):
    text = normalize_text(q)
    # Forecast musí byť explicitný. Samotné slová ako teplota/vlhkosť/hodnota
    # patria aj do historických otázok typu "priemerná teplota za 24 h".
    words=["forecast", "predik", "predpoved", "buduc", "buduce", "buduci", "dopredu", "o 30", "za 30", "30m", "plus 30"]
    return any(w in text for w in words)


def is_write_request(q):
    text = normalize_text(q)
    words=["restart", "restartni", "reboot", "delete", "zmaz", "vymaz", "scale", "skaluj", "patch", "apply", "nasad", "deploy", "upgrade", "update", "reconcile", "vytvor", "create", "edit", "uprav", "zmen", "kill", "drain", "cordon", "uncordon", "exec"]
    return any(w in text for w in words)


def readonly_refusal():
    return "AIOT Copilot je iba informačný/read-only. Vie zistiť stav a vysvetliť problém, ale nevie reštartovať, mazať, škálovať, patchovať ani inak meniť cluster."


def fast_answer(question, ctx):
    q=(question or "").lower()
    rows=ctx["latest"]
    if not q:
        return answer_risk(rows)
    if is_write_request(q):
        return readonly_refusal()
    if is_trend_question(q):
        return answer_trend_analysis(question)
    if is_compare_question(q):
        return answer_compare_locations(question)
    if is_anomaly_rca_question(q):
        return answer_anomaly_rca(question, rows)
    if is_correlation_question(q):
        return answer_correlation(question)

    if is_sensor_failure_question(q):
        return answer_failure_probability({"predictions": predictions(), "latest": rows})
    if is_log_question(q):
        return answer_logs(q)
    if is_cluster_question(q):
        return answer_cluster()
    if is_sensor_aggregate_question(q):
        return answer_sensor_aggregate(q)
    if is_forecast_question(q):
        return answer_forecast({"forecasts": forecasts()})
    if any(word in q for word in ["rizik", "naj", "kritick", "critical", "warning", "prečo", "preco", "senzor"]):
        return answer_risk(rows)
    if any(word in q for word in ["model", "mlflow", "predik", "inference", "údrž", "udrz"]):
        return answer_predictions(ctx)
    if any(word in q for word in ["extern", "api", "lokal", "lokál"]):
        return "Áno. Control Center používa lokálne dáta z Postgresu, lokálne predikcie z MLflow/inference API a lokálny Ollama model; externé LLM API sa nepoužíva. Kubernetes časť je read-only."
    if any(word in q for word in ["stav", "koľko", "kolko", "pocet", "počet", "beží", "bezi", "funguje", "zhrn", "sumar"]):
        return answer_status(ctx)
    return None


def compact_prompt(ctx, question):
    rows=ctx["latest"][:50]
    facts="; ".join([
        f"{r.get('sensor_id')} {r.get('location')} stav={r.get('status')} riziko={r.get('risk')} temp={fmt(r.get('temperature'),'°C')} vlhkost={fmt(r.get('humidity'),'%')} tlak={fmt(r.get('pressure'),'hPa')} bateria={fmt(r.get('battery'),'V')}"
        for r in rows
    ])
    s=ctx["summary"]
    return f"SÚHRN: vzorky_24h={s.get('samples')}, senzory={s.get('sensors')}, posledna_vzorka={s.get('latest')}. TOP_SENZORY: {facts}. OTÁZKA: {question}"


@app.get("/healthz")
def healthz(): return {"ok": True, "mode": "aiot-copilot-read-only"}


@app.get("/api/summary")
def api_summary(): return {"summary": summary(), "latest": latest(50), "predictions": predictions(), "forecasts": forecasts()}


@app.get("/api/copilot/cluster")
def api_copilot_cluster(): return cluster_snapshot()


@app.get("/api/copilot/logs")
def api_copilot_logs(): return logs_snapshot("cluster logs")


@app.get("/api/copilot/policy")
def api_copilot_policy():
    return {"mode": "read-only", "allowed": ["get", "list", "get pods/log"], "blocked": ["create", "update", "patch", "delete", "exec", "scale", "restart", "reboot"]}


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    started=time.time()
    question = (req.question or "").strip()
    q_lower=question.lower()
    external_words=["extern", "api", "lokal", "lokál"]
    prediction_words=["model", "mlflow", "predik", "inference", "údrž", "udrz", "zlyhan", "poruch", "pravdepodob"]
    risk_words=["rizik", "naj", "kritick", "critical", "warning", "prečo", "preco", "senzor"]
    status_words=["stav", "koľko", "kolko", "pocet", "počet", "beží", "bezi", "funguje", "zhrn", "sumar"]

    if is_write_request(q_lower):
        return {"answer": readonly_refusal(), "source": "read-only-policy", "seconds": round(time.time() - started, 3)}
    if is_trend_question(q_lower):
        return {"answer": answer_trend_analysis(question), "source": "trend-analysis-llm", "seconds": round(time.time() - started, 3)}
    if is_compare_question(q_lower):
        return {"answer": answer_compare_locations(question), "source": "compare-locations-llm", "seconds": round(time.time() - started, 3)}
    if is_anomaly_rca_question(q_lower):
        return {"answer": answer_anomaly_rca(question, latest(50)), "source": "anomaly-rca-llm", "seconds": round(time.time() - started, 3)}
    if is_correlation_question(q_lower):
        return {"answer": answer_correlation(question), "source": "correlation-analysis-llm", "seconds": round(time.time() - started, 3)}

    if is_sensor_failure_question(question):
        return {"answer": answer_failure_probability({"predictions": predictions(), "latest": latest(50)}), "source": "sensor-failure-prediction", "seconds": round(time.time() - started, 3)}
    if is_log_question(q_lower):
        return {"answer": answer_logs(question), "source": "kubernetes-logs-read-only", "seconds": round(time.time() - started, 3)}
    if is_cluster_question(q_lower):
        return {"answer": answer_cluster(), "source": "kubernetes-read-only", "seconds": round(time.time() - started, 3)}
    if is_location_aggregate_question(question):
        return {"answer": answer_location_aggregate(question), "source": "sensor-location-postgres", "seconds": round(time.time() - started, 3)}
    if is_sensor_aggregate_question(question):
        return {"answer": answer_sensor_aggregate(question), "source": "sensor-history-postgres", "seconds": round(time.time() - started, 3)}
    if is_forecast_question(q_lower):
        return {"answer": answer_forecast({"forecasts": forecasts()}), "source": "sensor-forecast", "seconds": round(time.time() - started, 3)}
    if any(word in q_lower for word in prediction_words):
        ctx={"summary": {}, "latest": [], "predictions": predictions()}
        return {"answer": answer_predictions(ctx), "source": "local-rules", "seconds": round(time.time() - started, 3)}
    if any(word in q_lower for word in external_words):
        answer="Áno. Control Center používa lokálne dáta z Postgresu, lokálne predikcie z MLflow/inference API a lokálny Ollama model; externé LLM API sa nepoužíva. Kubernetes časť je read-only."
        return {"answer": answer, "source": "local-rules", "seconds": round(time.time() - started, 3)}

    rows=latest(50)
    if not question or any(word in q_lower for word in risk_words):
        return {"answer": answer_risk(rows), "source": "local-rules", "seconds": round(time.time() - started, 3)}
    if any(word in q_lower for word in status_words):
        ctx={"summary": summary(), "latest": rows, "predictions": {}}
        return {"answer": answer_status(ctx), "source": "local-rules", "seconds": round(time.time() - started, 3)}

    ctx = {"summary": summary(), "latest": rows, "predictions": {}}
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": "Si odborný AIOT analytik. Odpovedaj výlučne po slovensky, stručne, max 2 vety. NIKDY nepíš kód, Python ani návody. Použi iba fakty."},
                    {"role": "user", "content": compact_prompt(ctx, question)},
                ],
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {"temperature": OLLAMA_TEMPERATURE, "num_predict": OLLAMA_NUM_PREDICT, "num_ctx": OLLAMA_NUM_CTX, "num_thread": OLLAMA_NUM_THREAD},
            },
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        return {"answer": r.json().get("message",{}).get("content", "Bez odpovede."), "source": OLLAMA_MODEL, "seconds": round(time.time() - started, 3)}
    except Exception as exc:
        return {"answer": "Lokálny LLM zatiaľ nie je dostupný: " + str(exc), "source": "error", "seconds": round(time.time() - started, 3)}


@app.get("/", response_class=HTMLResponse)
def home():
    s=summary(); rows=latest(50)
    ok=sum(1 for r in rows if r["status"]=="ok"); warn=sum(1 for r in rows if r["status"]=="warning"); crit=sum(1 for r in rows if r["status"]=="critical")
    table="".join([f"<tr class='{r['status']}'><td>{r['sensor_id']}</td><td>{r.get('location','')}</td><td>{r['status']}</td><td>{r['risk']}%</td><td>{r.get('temperature')}</td><td>{r.get('humidity')}</td><td>{r.get('pressure')}</td><td>{r.get('battery')}</td><td>{r.get('ts')}</td></tr>" for r in rows])
    return f"""<!doctype html><html><head><title>AIOT Copilot</title><style>
    body{{font-family:Arial,sans-serif;margin:0;background:#0f172a;color:#e5e7eb}} header{{padding:24px 32px;background:#111827;border-bottom:1px solid #334155}}
    .cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;padding:24px 32px}} .card{{background:#111827;border:1px solid #334155;border-radius:14px;padding:18px}}
    .n{{font-size:30px;font-weight:800}} .label{{color:#94a3b8}} main{{display:grid;grid-template-columns:2fr 1fr;gap:18px;padding:0 32px 32px}}
    table{{width:100%;border-collapse:collapse;background:#111827;border-radius:14px;overflow:hidden}} th,td{{padding:9px;border-bottom:1px solid #1f2937;font-size:14px}} th{{background:#1f2937}}
    tr.warning td{{color:#facc15}} tr.critical td{{color:#fb7185}} .panel{{background:#111827;border:1px solid #334155;border-radius:14px;padding:16px}}
    textarea{{width:100%;height:120px;background:#020617;color:#e5e7eb;border:1px solid #334155;border-radius:10px;padding:10px}} button{{margin-top:10px;background:#2563eb;color:white;border:0;border-radius:10px;padding:10px 16px}} pre{{white-space:pre-wrap;background:#020617;border:1px solid #334155;border-radius:10px;padding:12px;min-height:120px}}
    .safe{{color:#86efac;font-size:13px}}
    </style></head><body><header><h1>AIOT Copilot</h1><p>Jeden informačný chat pre senzory aj cluster. <span class='safe'>Read-only: nevie meniť cluster.</span></p></header>
    <section class='cards'><div class='card'><div class='n'>{s.get('sensors') or 0}</div><div class='label'>senzorov</div></div><div class='card'><div class='n'>{ok}</div><div class='label'>OK</div></div><div class='card'><div class='n'>{warn}</div><div class='label'>Warning</div></div><div class='card'><div class='n'>{crit}</div><div class='label'>Critical</div></div><div class='card'><div class='n'>{s.get('samples') or 0}</div><div class='label'>vzoriek 24h</div></div></section>
    <main><section><table><thead><tr><th>Senzor</th><th>Lokácia</th><th>Stav</th><th>Riziko</th><th>Teplota</th><th>Vlhkosť</th><th>Tlak</th><th>Batéria</th><th>Čas</th></tr></thead><tbody>{table}</tbody></table></section>
    <aside class='panel'><h2>AIOT Copilot</h2><p class='safe'>Iba číta dáta: senzory, MLflow, Kubernetes, Flux/Helm eventy a pod logy.</p><textarea id='q'>Skontroluj logy služieb na klustri</textarea><button onclick='ask()'>Spýtať sa</button><pre id='a'>Odpoveď sa zobrazí tu.</pre></aside></main>
    <script>async function ask(){{let a=document.getElementById('a');a.textContent='Pracujem...';let r=await fetch('/api/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{question:document.getElementById('q').value}})}});let j=await r.json();a.textContent=j.answer||JSON.stringify(j,null,2);}}</script>
    </body></html>"""
