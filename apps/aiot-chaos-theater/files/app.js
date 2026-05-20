let currentState = null;
let replayTimer = null;
let replayIndex = -1;

const phaseClass = (phase) => {
  if (!phase || phase === 'never run') return 'idle';
  if (['Succeeded', 'Completed', 'Pass'].includes(phase)) return 'success';
  if (['Failed', 'Error', 'Fail'].includes(phase)) return 'danger';
  return 'running';
};

const healthText = (h) => h === 'red' ? 'impact' : h === 'yellow' ? 'recovery' : 'healthy';
const esc = (v) => String(v ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const fmtTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('sk-SK', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
};
const shortPod = (name) => name ? name.replace(/^aiot-/, '') : '—';

function renderHero(state) {
  const wf = state.latestWorkflow;
  const impact = state.impact || {};
  const name = wf ? wf.baseName : 'čakám na Litmus';
  const phase = impact.verdict || wf?.phase || 'idle';
  document.getElementById('heroExperiment').textContent = name;
  const status = document.getElementById('heroStatus');
  status.textContent = wf ? phase : 'waiting';
  status.className = `pill ${phaseClass(phase)}`;
  document.getElementById('lastUpdated').textContent = `updated ${fmtTime(state.generatedAt)}`;
}

function renderFocus(state) {
  const wf = state.latestWorkflow || {};
  const impact = state.impact || {};
  const running = wf.phase && !['Succeeded', 'Failed', 'Error'].includes(wf.phase);
  const recovery = impact.recoverySeconds != null && impact.recoverySeconds > 0 ? `${impact.recoverySeconds}s` : '—';
  const items = [
    ['Stav', impact.verdict || wf.phase || 'idle', ''],
    ['Cieľ', impact.target || wf.target || '—', ''],
    ['Zásah', impact.deletedPod ? shortPod(impact.deletedPod) : (running ? 'prebieha' : '—'), 'small'],
    ['Obnova', impact.verdict ? `PASS · ${impact.score || 100}` : recovery, '']
  ];
  document.getElementById('focus').innerHTML = items.map(([label, value, cls]) => `<div class="focus-item"><div class="focus-label">${esc(label)}</div><div class="focus-value ${cls}">${esc(value)}</div></div>`).join('');
}

function renderPipeline(state, highlight = null) {
  const target = state.impact?.target;
  document.getElementById('topology').innerHTML = (state.components || []).map(c => {
    const cls = `${c.health || 'green'} ${c.id === target ? 'target' : ''} ${c.id === highlight ? 'replay-hit' : ''}`;
    return `<article class="node ${cls}">
      <div class="node-icon">${c.icon || '◦'}</div>
      <div class="node-name">${esc(c.title)}</div>
      <div class="node-ready">${esc(c.ready)}/${esc(c.desired || '?')} ready</div>
      <div class="health">${healthText(c.health)}</div>
    </article>`;
  }).join('');
}

function importantEvents(state) {
  const keep = new Set(['Killing', 'SuccessfulCreate', 'ChaosInject', 'Summary', 'Pass', 'Fail', 'ChaosEngineCompleted', 'ChaosEngineStopped', 'WorkflowSucceeded']);
  return (state.timeline || []).filter(e => keep.has(e.reason) || ['Pod deleted', 'Replacement pod created', 'Result PASS', 'Result FAIL', 'Fault injected', 'Experiment finished'].includes(e.title)).slice(-12);
}

function cleanMessage(ev) {
  if (ev.reason === 'Killing') return shortPod(ev.object);
  if (ev.reason === 'SuccessfulCreate' && ev.message?.includes('Created pod:')) return shortPod(ev.message.split('Created pod:')[1].trim().split(/\s+/)[0]);
  if (ev.reason === 'Pass') return 'experiment prešiel úspešne';
  if (ev.reason === 'Fail') return 'experiment zlyhal';
  if (ev.reason === 'ChaosInject') return 'Litmus práve aplikuje fault';
  return ev.message || '';
}

function renderTimeline(state, activeIndex = -1) {
  const events = importantEvents(state);
  const el = document.getElementById('timeline');
  if (!events.length) {
    el.innerHTML = '<div class="empty">Spusť experiment v Litmuse. Tu sa zobrazí jednoduchý priebeh.</div>';
    return;
  }
  el.innerHTML = events.map((ev, idx) => `<div class="event ${esc(ev.level || 'info')} ${idx === activeIndex ? 'replay-hit' : ''}">
    <div class="event-time">${fmtTime(ev.time)}</div>
    <div>${ev.icon || '•'}</div>
    <div><div class="event-title">${esc(ev.title || ev.reason)}</div><div class="event-msg">${esc(cleanMessage(ev))}</div></div>
    <div class="event-comp">${esc(ev.component || '')}</div>
  </div>`).join('');
}

function renderExperiments(state) {
  document.getElementById('experiments').innerHTML = (state.experiments || []).map(e => {
    const last = e.verdict ? `${e.verdict} ${e.score || ''}` : (e.status || 'never');
    return `<span class="exp">${esc(e.label)} · ${esc(last)}</span>`;
  }).join('');
}

function render(state) {
  currentState = state;
  renderHero(state);
  renderFocus(state);
  renderPipeline(state);
  renderTimeline(state);
  renderExperiments(state);
}

async function loadState() {
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    render(body);
  } catch (err) {
    document.getElementById('heroExperiment').textContent = 'Theater API error';
    const status = document.getElementById('heroStatus');
    status.textContent = err.message;
    status.className = 'pill danger';
  }
}

function startReplay() {
  const events = importantEvents(currentState || {});
  if (!events.length) return;
  if (replayTimer) clearInterval(replayTimer);
  replayIndex = 0;
  replayTimer = setInterval(() => {
    const ev = events[replayIndex];
    renderPipeline(currentState, ev?.component);
    renderTimeline(currentState, replayIndex);
    replayIndex += 1;
    if (replayIndex >= events.length) {
      clearInterval(replayTimer);
      replayTimer = null;
      setTimeout(() => render(currentState), 700);
    }
  }, 700);
}

document.getElementById('replayBtn').addEventListener('click', startReplay);
loadState();
setInterval(loadState, 3000);
