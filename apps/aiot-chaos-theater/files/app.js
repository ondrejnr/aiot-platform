let currentState = null;
let replayTimer = null;
let replayIndex = -1;
let selectedComponentId = null;

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
const timeMs = (iso) => {
  const t = new Date(iso || '').getTime();
  return Number.isFinite(t) ? t : null;
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

function getSelectedComponent(state) {
  const components = state.components || [];
  const target = state.impact?.target || state.latestWorkflow?.target;
  if (!selectedComponentId) selectedComponentId = target || components[0]?.id || null;
  return components.find(c => c.id === selectedComponentId) || components.find(c => c.id === target) || components[0] || null;
}

function renderPipeline(state, highlight = null) {
  const target = state.impact?.target;
  const selected = getSelectedComponent(state)?.id;
  document.getElementById('topology').innerHTML = (state.components || []).map(c => {
    const cls = `${c.health || 'green'} ${c.id === target ? 'target' : ''} ${c.id === highlight ? 'replay-hit' : ''} ${c.id === selected ? 'selected' : ''}`;
    return `<button class="node ${cls}" type="button" data-component="${esc(c.id)}" aria-label="Detail ${esc(c.title)}">
      <div class="node-icon">${c.icon || '◦'}</div>
      <div class="node-name">${esc(c.title)}</div>
      <div class="node-ready">${esc(c.ready)}/${esc(c.desired || '?')} ready</div>
      <div class="health">${healthText(c.health)}</div>
    </button>`;
  }).join('');
  document.querySelectorAll('.node[data-component]').forEach(node => {
    node.addEventListener('click', () => {
      selectedComponentId = node.getAttribute('data-component');
      render(currentState);
    });
  });
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

function eventLane(ev, state) {
  if (ev.component) return ev.component;
  if (['Killing', 'SuccessfulCreate'].includes(ev.reason)) return state.impact?.target || state.latestWorkflow?.target || 'experiment';
  if (ev.reason === 'ChaosInject') return state.impact?.target || state.latestWorkflow?.target || 'experiment';
  return 'experiment';
}

function renderFlowGraph(state, activeIndex = -1) {
  const el = document.getElementById('flowGraph');
  if (!el) return;
  const events = importantEvents(state).filter(e => timeMs(e.time) !== null);
  if (!events.length) {
    el.innerHTML = '<div class="empty">Po spustení experimentu sa tu zobrazí časový graf udalostí.</div>';
    return;
  }
  const stamps = events.map(e => timeMs(e.time)).filter(t => t !== null);
  let start = Math.min(...stamps);
  let end = Math.max(...stamps);
  if (end <= start) end = start + 60000;
  const target = state.impact?.target || state.latestWorkflow?.target;
  const selected = getSelectedComponent(state)?.id;
  const laneDefs = [{id: 'experiment', title: 'Experiment', icon: '🧪'}].concat(state.components || []);
  const activeLaneIds = new Set(['experiment', target, selected].filter(Boolean));
  events.forEach(e => activeLaneIds.add(eventLane(e, state)));
  const lanes = laneDefs.filter(l => activeLaneIds.has(l.id));
  const dotsByLane = new Map(lanes.map(l => [l.id, []]));
  events.forEach((ev, idx) => {
    const lane = eventLane(ev, state);
    if (!dotsByLane.has(lane)) return;
    const pct = Math.max(0, Math.min(100, ((timeMs(ev.time) - start) / (end - start)) * 100));
    const cls = ev.level === 'danger' ? 'danger' : ev.level === 'warn' ? 'warn' : ev.level === 'success' ? 'success' : 'info';
    dotsByLane.get(lane).push(`<span class="flow-dot ${cls} ${idx === activeIndex ? 'active' : ''}" style="left:${pct}%" title="${esc(fmtTime(ev.time) + ' · ' + (ev.title || ev.reason) + ' · ' + cleanMessage(ev))}">${ev.icon || '•'}</span>`);
  });
  const rows = lanes.map(l => `<div class="flow-row">
    <div class="flow-label"><span>${l.icon || '•'}</span><b>${esc(l.title || l.id)}</b></div>
    <div class="flow-track"><span class="flow-line"></span>${(dotsByLane.get(l.id) || []).join('')}</div>
  </div>`).join('');
  const running = state.latestWorkflow && !['Succeeded', 'Failed', 'Error'].includes(state.latestWorkflow.phase);
  el.innerHTML = `<div class="flow-axis"><span>${fmtTime(new Date(start).toISOString())}</span><span>${running ? 'live' : fmtTime(new Date(end).toISOString())}</span></div>${rows}<div class="flow-legend"><span><i class="legend-dot danger"></i> zásah</span><span><i class="legend-dot warn"></i> obnova</span><span><i class="legend-dot success"></i> hotovo</span></div>`;
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

function podStateClass(pod) {
  if (pod.ready && pod.phase === 'Running') return 'ok';
  if (pod.phase === 'Pending' || pod.phase === 'ContainerCreating') return 'wait';
  return 'bad';
}

function renderComponentDetail(state) {
  const comp = getSelectedComponent(state);
  const el = document.getElementById('componentDetail');
  if (!comp) {
    el.innerHTML = '<div class="empty">Klikni na komponent v pipeline.</div>';
    return;
  }
  const impact = state.impact || {};
  const isTarget = comp.id === impact.target;
  const pods = (comp.pods || []).slice(0, 10);
  const more = (comp.pods || []).length > pods.length ? `<div class="tiny">+ ďalších ${(comp.pods || []).length - pods.length} podov</div>` : '';
  const events = importantEvents(state).filter(e => e.component === comp.id).slice(-4);
  const podRows = pods.length ? pods.map(p => `<div class="pod-row ${podStateClass(p)}">
    <span class="pod-led"></span>
    <span class="pod-name">${esc(shortPod(p.name))}</span>
    <span>${esc(p.ready ? 'ready' : p.phase || 'not ready')}</span>
    <span>${esc((p.restarts || 0) + ' restarts')}</span>
  </div>`).join('') + more : '<div class="empty small-empty">Žiadne pody.</div>';
  const impactHtml = isTarget ? `<div class="detail-box impact-box">
      <div class="detail-label">Chaos zásah</div>
      <div><b>Zmazaný:</b> ${esc(shortPod(impact.deletedPod))}</div>
      <div><b>Náhrada:</b> ${esc(shortPod(impact.replacementPod))}</div>
      <div><b>Výsledok:</b> ${esc(impact.verdict || 'prebieha')}${impact.score ? ' · ' + esc(impact.score) : ''}</div>
    </div>` : `<div class="detail-box"><div class="detail-label">Chaos zásah</div><div>Momentálne bez zásahu.</div></div>`;
  const eventHtml = events.length ? events.map(e => `<div class="mini-event"><span>${e.icon || '•'}</span><span>${fmtTime(e.time)}</span><b>${esc(e.title || e.reason)}</b></div>`).join('') : '<div class="tiny">Pre tento komponent nie sú posledné chaos udalosti.</div>';
  el.innerHTML = `<div class="detail-head">
      <div><div class="detail-kicker">Detail komponentu</div><h3>${comp.icon || ''} ${esc(comp.title)}</h3></div>
      <div class="detail-status ${esc(comp.health || 'green')}">${healthText(comp.health)}</div>
    </div>
    <div class="detail-grid">
      <div class="detail-box"><div class="detail-label">Stav</div><div class="detail-big">${esc(comp.ready)}/${esc(comp.desired || '?')}</div><div class="tiny">ready replík</div></div>
      <div class="detail-box"><div class="detail-label">Workload</div><div>${esc(comp.namespace)} / ${esc(comp.name)}</div><div class="tiny">${esc(comp.kind)} · ${esc(comp.subtitle)}</div></div>
      ${impactHtml}
    </div>
    <div class="detail-columns">
      <div><div class="detail-label">Pody</div><div class="pod-list">${podRows}</div></div>
      <div><div class="detail-label">Posledné udalosti</div><div class="mini-events">${eventHtml}</div></div>
    </div>`;
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
  renderComponentDetail(state);
  renderFlowGraph(state);
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
    renderFlowGraph(currentState, replayIndex);
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
