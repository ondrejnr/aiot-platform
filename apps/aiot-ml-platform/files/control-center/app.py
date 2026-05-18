import json, os, time
import psycopg
from psycopg.rows import dict_row
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="AIOT Control Center")

class ChatRequest(BaseModel):
    question: str = ""

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama.local-ai.svc.cluster.local:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", "4"))
INFERENCE_URL = os.getenv("INFERENCE_URL", "http://aiot-maintenance-api.aiot.svc.cluster.local:8080")
INFERENCE_MODEL_NAME = os.getenv("INFERENCE_MODEL_NAME", "aiot-maintenance-predictor")


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


def fast_answer(question, ctx):
    q=(question or "").lower()
    rows=ctx["latest"]
    if not q:
        return answer_risk(rows)
    if any(word in q for word in ["rizik", "naj", "kritick", "critical", "warning", "prečo", "preco", "senzor"]):
        return answer_risk(rows)
    if any(word in q for word in ["model", "mlflow", "predik", "inference", "údrž", "udrz"]):
        return answer_predictions(ctx)
    if any(word in q for word in ["extern", "api", "lokal", "lokál"]):
        return "Áno. Control Center používa lokálne dáta z Postgresu, lokálne predikcie z MLflow/inference API a lokálny Ollama model; externé LLM API sa nepoužíva."
    if any(word in q for word in ["stav", "koľko", "kolko", "pocet", "počet", "beží", "bezi", "funguje", "zhrn", "sumar"]):
        return answer_status(ctx)
    return None


def compact_prompt(ctx, question):
    rows=ctx["latest"][:5]
    facts="; ".join([
        f"{r.get('sensor_id')} {r.get('location')} stav={r.get('status')} riziko={r.get('risk')} temp={fmt(r.get('temperature'),'°C')} vlhkost={fmt(r.get('humidity'),'%')} tlak={fmt(r.get('pressure'),'hPa')} bateria={fmt(r.get('battery'),'V')}"
        for r in rows
    ])
    s=ctx["summary"]
    return f"SÚHRN: vzorky_24h={s.get('samples')}, senzory={s.get('sensors')}, posledna_vzorka={s.get('latest')}. TOP_SENZORY: {facts}. OTÁZKA: {question}"


@app.get("/healthz")
def healthz(): return {"ok": True}


@app.get("/api/summary")
def api_summary(): return {"summary": summary(), "latest": latest(50), "predictions": predictions()}


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    started=time.time()
    question = (req.question or "").strip()
    q_lower=question.lower()
    external_words=["extern", "api", "lokal", "lokál"]
    prediction_words=["model", "mlflow", "predik", "inference", "údrž", "udrz"]
    risk_words=["rizik", "naj", "kritick", "critical", "warning", "prečo", "preco", "senzor"]
    status_words=["stav", "koľko", "kolko", "pocet", "počet", "beží", "bezi", "funguje", "zhrn", "sumar"]

    if any(word in q_lower for word in prediction_words):
        ctx={"summary": {}, "latest": [], "predictions": predictions()}
        return {"answer": answer_predictions(ctx), "source": "local-rules", "seconds": round(time.time() - started, 3)}
    if any(word in q_lower for word in external_words):
        answer="Áno. Control Center používa lokálne dáta z Postgresu, lokálne predikcie z MLflow/inference API a lokálny Ollama model; externé LLM API sa nepoužíva."
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
                    {"role": "system", "content": "Si lokálny AIOT asistent. Odpovedaj výlučne po slovensky, stručne, max 3 vety, iba z poskytnutých faktov."},
                    {"role": "user", "content": compact_prompt(ctx, question)},
                ],
                "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.1, "num_predict": 70, "num_ctx": 512, "num_thread": OLLAMA_NUM_THREAD},
            },
            timeout=60,
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
    return f"""<!doctype html><html><head><title>AIOT Control Center</title><style>
    body{{font-family:Arial,sans-serif;margin:0;background:#0f172a;color:#e5e7eb}} header{{padding:24px 32px;background:#111827;border-bottom:1px solid #334155}}
    .cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;padding:24px 32px}} .card{{background:#111827;border:1px solid #334155;border-radius:14px;padding:18px}}
    .n{{font-size:30px;font-weight:800}} .label{{color:#94a3b8}} main{{display:grid;grid-template-columns:2fr 1fr;gap:18px;padding:0 32px 32px}}
    table{{width:100%;border-collapse:collapse;background:#111827;border-radius:14px;overflow:hidden}} th,td{{padding:9px;border-bottom:1px solid #1f2937;font-size:14px}} th{{background:#1f2937}}
    tr.warning td{{color:#facc15}} tr.critical td{{color:#fb7185}} .panel{{background:#111827;border:1px solid #334155;border-radius:14px;padding:16px}}
    textarea{{width:100%;height:120px;background:#020617;color:#e5e7eb;border:1px solid #334155;border-radius:10px;padding:10px}} button{{margin-top:10px;background:#2563eb;color:white;border:0;border-radius:10px;padding:10px 16px}} pre{{white-space:pre-wrap;background:#020617;border:1px solid #334155;border-radius:10px;padding:12px;min-height:120px}}
    </style></head><body><header><h1>AIOT Control Center</h1><p>Lokálne AI/ML bez externých LLM API</p></header>
    <section class='cards'><div class='card'><div class='n'>{s.get('sensors') or 0}</div><div class='label'>senzorov</div></div><div class='card'><div class='n'>{ok}</div><div class='label'>OK</div></div><div class='card'><div class='n'>{warn}</div><div class='label'>Warning</div></div><div class='card'><div class='n'>{crit}</div><div class='label'>Critical</div></div><div class='card'><div class='n'>{s.get('samples') or 0}</div><div class='label'>vzoriek 24h</div></div></section>
    <main><section><table><thead><tr><th>Senzor</th><th>Lokácia</th><th>Stav</th><th>Riziko</th><th>Teplota</th><th>Vlhkosť</th><th>Tlak</th><th>Batéria</th><th>Čas</th></tr></thead><tbody>{table}</tbody></table></section>
    <aside class='panel'><h2>AI otázka</h2><textarea id='q'>Ktoré senzory sú najrizikovejšie a prečo?</textarea><button onclick='ask()'>Spýtať sa</button><pre id='a'>Odpoveď sa zobrazí tu.</pre></aside></main>
    <script>async function ask(){{let a=document.getElementById('a');a.textContent='Pracujem...';let r=await fetch('/api/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{question:document.getElementById('q').value}})}});let j=await r.json();a.textContent=j.answer||JSON.stringify(j,null,2);}}</script>
    </body></html>"""
