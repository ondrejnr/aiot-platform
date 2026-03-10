import json, time, logging, hashlib, re
import requests, redis
from flask import Flask, jsonify, request as flask_request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rag-worker")

REDIS_HOST = "redis-master.aiot.svc.cluster.local"
CEREBRUS_URL = "http://api-gateway.aiot.svc.cluster.local:8080"
bank  = redis.Redis(host=REDIS_HOST, port=6379, db=5, decode_responses=True)
rd    = redis.Redis(host=REDIS_HOST, port=6379, db=3, decode_responses=True)
ANSWER_TTL = 600
BANK_TTL   = 120
app   = Flask(__name__)
stats = {"queries": 0, "cache_hits": 0, "bank_hits": 0, "llm_calls": 0, "blocked": 0, "start_time": time.time()}

SIMPLE_KW = ["summary","status","overview","suhrn","prehlad","how many","kolko","pocet","total","celkom","critical","kritick","warning","varov","alarm","ok machines","list","zoznam","stav","factory"]
COMPLEX_KW = ["why","preco","cause","pricina","recommend","odporuc","predict","predpoved","trend","analyze","analyz","compare","porovnaj","explain","vysvetli","what if","should","plan","optimiz","improve","suggest"]
MACH_RE = re.compile(r'(pump|turbine|motor|compressor|conveyor|generator)[-_]?\d+', re.I)
JUNK_RE = re.compile(r'(follow.?up|suggest.*question|### task|relevant question)', re.I)

def is_junk(q):
    return bool(JUNK_RE.search(q))

def is_complex(q):
    return any(k in q.lower() for k in COMPLEX_KW)

def is_simple(q):
    if is_complex(q): return False
    ql = q.lower()
    if MACH_RE.search(ql): return True
    return any(k in ql for k in SIMPLE_KW)

def answer_from_bank(q):
    ql = q.lower()
    try:
        raw = bank.get("bank:summary")
        if not raw: return None
        s = json.loads(raw)
        m = MACH_RE.search(ql)
        if m:
            mid = m.group(0).replace("_", "-")
            mraw = bank.get(f"bank:machines:{mid}")
            if not mraw: return f"Stroj {mid} sa nenasiel."
            md = json.loads(mraw); mt = md.get("metrics", {})
            lines = [f"{mid} | typ: {md.get('machine_type','-')} | stav: {md.get('status','-')}",
                     f"Teplota: {mt.get('temperature','-')}C | Vibracie: {mt.get('vibration','-')}mm/s | Tlak: {mt.get('pressure','-')}bar | RPM: {mt.get('rpm','-')}"]
            for v in md.get("violations",[]): lines.append(f"Porusenia: {v['metric']}={v['value']}")
            hist = bank.lrange(f"bank:history:{mid}", 0, 4)
            if hist:
                lines.append("Historia (poslednych 5):")
                for e in hist:
                    d = json.loads(e); lines.append(f"  T={d.get('temperature','-')} V={d.get('vibration','-')} P={d.get('pressure','-')} [{d.get('status','-')}]")
            return "\n".join(lines)
        total,ok,warn,crit = s.get("total",0),s.get("ok",0),s.get("warning",0),s.get("critical",0)
        if any(k in ql for k in ["summary","status","overview","suhrn","prehlad","total","celkom","factory","stav"]):
            cn = ", ".join(s.get("critical_machines",[])[:10])
            return f"Tovarena — prehlad:\nCelkom: {total} strojov | OK: {ok} | Warning: {warn} | Critical: {crit}\nTop critical: {cn}{'...' if crit>10 else ''}"
        if any(k in ql for k in ["critical","kritick","alarm"]):
            return f"Kriticke stroje ({crit}):\n" + "\n".join(f"  {n}" for n in s.get("critical_machines",[])[:20])
        if any(k in ql for k in ["warning","varov","warn"]):
            return f"Warning stroje ({warn}):\n" + "\n".join(f"  {n}" for n in s.get("warning_machines",[])[:20])
        if any(k in ql for k in ["how many","kolko","pocet"]):
            return f"Celkom {total} strojov: {ok} OK, {warn} warning, {crit} critical."
    except Exception as e: log.error(f"Bank error: {e}")
    return None

FOLLOWUP_ANSWERS = [
    "What is the factory status?",
    "Show me critical machines",
    "Which machines have warnings?",
    "How many machines are running?",
    "Show turbine-0340 details"
]

def call_cerebrus(query):
    try:
        r = requests.post(f"{CEREBRUS_URL}/v1/chat/completions",
            json={"model":"cerebrus-aiot","messages":[{"role":"user","content":query}]}, timeout=60)
        if r.status_code == 200: return r.json()["choices"][0]["message"]["content"]
        log.warning(f"Cerebrus HTTP {r.status_code}")
    except Exception as e: log.error(f"Cerebrus error: {e}")
    return None

@app.route("/")
def root(): return jsonify({"service":"RAG Worker v9","mode":"bank-first+junk-filter"})

@app.route("/status")
def status_ep():
    try:
        raw = bank.get("bank:summary")
        if raw: return jsonify({"summary":json.loads(raw),"source":"bank"})
    except: pass
    return jsonify({"error":"No data"}), 404

@app.route("/v1/chat/completions", methods=["POST"])
def chat():
    msgs = (flask_request.json or {}).get("messages", [])
    user = [m for m in msgs if m.get("role") == "user"]
    q = user[-1]["content"].strip() if user else "summary"
    ck = f"rag:chat:{hashlib.sha256(q.lower().strip().encode()).hexdigest()[:16]}"

    # Block junk queries (follow-up suggestions etc.)
    if is_junk(q):
        stats["blocked"] += 1
        content = "\n".join(FOLLOWUP_ANSWERS)
        source = "blocked-junk"
        log.info(f"query='{q[:50]}' source={source}")
        return jsonify({"id":f"rag-{int(time.time())}","object":"chat.completion","model":"cerebrus-aiot",
            "choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}})

    cached = rd.get(ck)
    if cached:
        stats["cache_hits"] += 1; content = cached; source = "cache"
    elif is_simple(q):
        ba = answer_from_bank(q)
        if ba:
            stats["bank_hits"] += 1; rd.setex(ck, BANK_TTL, ba); content = ba; source = "bank"
        else:
            stats["llm_calls"] += 1; content = call_cerebrus(q) or "Inicializujem..."; source = "llm"
            if content and "Error" not in content: rd.setex(ck, ANSWER_TTL, content)
    else:
        stats["llm_calls"] += 1; content = call_cerebrus(q) or "Inicializujem..."; source = "llm"
        if content and "Error" not in content: rd.setex(ck, ANSWER_TTL, content)
    stats["queries"] += 1
    log.info(f"query='{q[:50]}' source={source}")
    return jsonify({"id":f"rag-{int(time.time())}","object":"chat.completion","model":"cerebrus-aiot",
        "choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":"stop"}],
        "usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}})

@app.route("/v1/models")
def models(): return jsonify({"object":"list","data":[{"id":"cerebrus-aiot","object":"model"}]})
@app.route("/stats")
def stats_ep2(): return jsonify({**stats, "uptime_s": int(time.time()-stats["start_time"])})

log.info("RAG Worker v9 — bank-first, junk-filter, complex->LLM")
app.run(host="0.0.0.0", port=7000)
