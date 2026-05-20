let currentState = null;
let replayTimer = null;
let replayIndex = -1;

const phaseClass = (phase) => {
  if (!phase || phase === 'never run') return 'idle';
  if (phase === 'Succeeded' || phase === 'Completed' || phase === 'Pass') return 'success';
  if (phase === 'Failed' || phase === 'Error' || phase === 'Fail') return 'danger';
  return 'running';
};

const fmtTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString('sk-SK', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));

function renderHero(state) {
  const wf = state.latestWorkflow;
  const impact = state.impact || {};
  const name = wf ? wf.baseName : 'čakám na Litmus experiment';
  const phase = wf ? wf.phase : 'idle';
  document.getElementById('heroExperiment').textContent = name;
  const status = document.getElementById('heroStatus');
  status.textContent = wf ? `${phase}${impact.verdict ? ' · ' + impact.verdict : ''}` : 'waiting';
  status.className = `status-pill ${phaseClass(impact.verdict || phase)}`;
  document.getElementById('lastUpdated').textContent = `updated ${fmtTime(state.generatedAt)} · namespace ${state.namespace} · read-only`;
}

function renderExperiments(state) {
  const el = document.getElementById('experiments');
  el.innerHTML = (state.experiments || []).map(exp => {
    const phase = exp.status || 'never run';
    const verdict = exp.verdict ? `${exp.verdict}${exp.score ? ' ' + exp.score : ''}` : phase;
    return `<article class="exp-card">
      <div class="exp-title">${esc(exp.label)}</div>
      <div class="exp-meta">
        <span class="chip">target: ${esc(exp.target)}</span>
        <span class="chip">fault: ${esc(exp.fault)}</span>
        <span class="chip">last: ${esc(verdict)}</span>
      </div>
    </article>`;
  }).join('');
}

function podDot(pod) {
  const cls = pod.ready && pod.phase === 'Running' ? '' : (pod.phase === 'Pending' || pod.phase === 'ContainerCreating' ? 'wait' : 'bad');
  return `<span class="pod-dot ${cls}" title="${esc(pod.name)} · ${esc(pod.phase)} · ready=${pod.ready}"></span>`;
}

function renderTopology(state, highlightComponent = null) {
  const target = state.impact?.target;
  const el = document.getElementById('topology');
  el.innerHTML = (state.components || []).map(comp => {
    const desired = comp.desired || 0;
    const ready = comp.ready || 0;
    const pct = desired > 0 ? Math.max(0, Math.min(100, Math.round((ready / desired) * 100))) : 0;
    const targetCls = comp.id === target ? 'target' : '';
    const replayCls = comp.id === highlightComponent ? 'replay-hit' : '';
    const pods = (comp.pods || []).slice(0, 50).map(podDot).join('');
    return `<article class="node ${esc(comp.health)} ${targetCls} ${replayCls}" data-component="${esc(comp.id)}">
      <div class="node-top">
        <div>
          <div class="node-title">${esc(comp.title)}</div>
          <div class="node-sub">${esc(comp.subtitle)} · ${esc(comp.kind)}</div>
        </div>
        <div class="node-icon">${comp.icon || '◦'}</div>
      </div>
      <div class="ready">${ready}/${desired || '?'} <small>ready</small></div>
      <div class="bar"><span style="width:${pct}%"></span></div>
      <div class="node-sub">${esc(comp.namespace)} / ${esc(comp.name)}</div>
      <div class="pods">${pods}</div>
    </article>`;
  }).join('');
}

function renderImpact(state) {
  const impact = state.impact || {};
  const wf = state.latestWorkflow || {};
  const items = [
    ['Experiment', wf.baseName || '—'],
    ['Target', impact.target || wf.target || '—'],
    ['Deleted pod', impact.deletedPod || '—'],
    ['Replacement pod', impact.replacementPod || '—'],
    ['Recovery estimate', impact.recoverySeconds != null ? `${impact.recoverySeconds}s` : '—'],
    ['Result', impact.verdict ? `${impact.verdict}${impact.score ? ' · score ' + impact.score : ''}` : '—']
  ];
  document.getElementById('impact').innerHTML = items.map(([k, v]) => `<div class="impact-item"><div class="impact-label">${esc(k)}</div><div class="impact-value">${esc(v)}</div></div>`).join('');
}

function renderWorkflowNodes(state) {
  const nodes = state.latestWorkflow?.nodes || [];
  const el = document.getElementById('workflowNodes');
  if (!nodes.length) {
    el.innerHTML = '<div class="empty">Žiadny workflow zatiaľ nebeží.</div>';
    return;
  }
  el.innerHTML = nodes.slice(-8).map(node => {
    const icon = node.phase === 'Succeeded' ? '✅' : node.phase === 'Running' ? '▶️' : node.phase === 'Failed' ? '🔴' : '•';
    return `<div class="wf-node"><span>${icon}</span><span>${esc(node.displayName || node.type)}</span><span class="wf-phase">${esc(node.phase || '')}</span></div>`;
  }).join('');
}

function renderTimeline(state, activeIndex = -1) {
  const events = state.timeline || [];
  const el = document.getElementById('timeline');
  if (!events.length) {
    el.innerHTML = '<div class="empty">Zatiaľ nemám chaos udalosti. Spusť experiment v Litmuse a Theater začne skladať príbeh.</div>';
    return;
  }
  const slice = events.slice(-45);
  el.innerHTML = slice.map((ev, idx) => {
    const glow = idx === activeIndex ? ' replay-hit' : '';
    return `<div class="event ${esc(ev.level || 'info')}${glow}">
      <div class="event-time">${fmtTime(ev.time)}</div>
      <div class="event-icon">${ev.icon || '•'}</div>
      <div><div class="event-title">${esc(ev.title || ev.reason)}</div><div class="event-msg">${esc(ev.message || '')}</div></div>
      <div class="event-comp">${esc(ev.component || ev.kind || '')}</div>
    </div>`;
  }).join('');
}

function render(state) {
  currentState = state;
  renderHero(state);
  renderExperiments(state);
  renderTopology(state);
  renderImpact(state);
  renderWorkflowNodes(state);
  renderTimeline(state);
}

async function loadState() {
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
  } catch (err) {
    document.getElementById('heroExperiment').textContent = 'Theater API error';
    const status = document.getElementById('heroStatus');
    status.textContent = err.message;
    status.className = 'status-pill danger';
  }
}

function startReplay() {
  if (!currentState?.timeline?.length) return;
  if (replayTimer) clearInterval(replayTimer);
  const events = currentState.timeline.slice(-45);
  replayIndex = 0;
  replayTimer = setInterval(() => {
    const ev = events[replayIndex];
    renderTopology(currentState, ev?.component);
    renderTimeline(currentState, replayIndex);
    replayIndex += 1;
    if (replayIndex >= events.length) {
      clearInterval(replayTimer);
      replayTimer = null;
      setTimeout(() => render(currentState), 800);
    }
  }, 650);
}

document.getElementById('replayBtn').addEventListener('click', startReplay);
loadState();
setInterval(loadState, 2500);
