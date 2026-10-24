/* ─────────────────────────────────────────────────────────
   Strategic Intelligence System — Frontend Logic
   ─────────────────────────────────────────────────────────
   Handles:
   - File upload with drag-and-drop
   - Case creation
   - SSE event streaming
   - Live Digital Twin visualization
   - Agent timeline
   - Hypothesis cards with confidence bars
   - Simulation table
   - Devil's Advocate challenges
   - Final decision report with evidence linking
   - Evidence drawer
   ───────────────────────────────────────────────────────── */

const API = '';   // same-origin

// ── State ─────────────────────────────────────────────────
const state = {
  docId: null,
  caseId: null,
  hypotheses: {},    // id → hypothesis object
  evidence: {},      // id → evidence object
  simulations: [],
  entityCounts: { Company: 0, Product: 0, CustomerSegment: 0, Competitor: 0, Market: 0 },
};

// ── DOM references ─────────────────────────────────────────
const $ = id => document.getElementById(id);
const setupPanel   = $('setup-panel');
const workspace    = $('workspace');
const dropZone     = $('drop-zone');
const fileInput    = $('file-input');
const uploadStatus = $('upload-status');
const questionInput= $('question-input');
const startBtn     = $('start-btn');
const statusDot    = $('status-dot');
const statusText   = $('status-text');
const iterBadge    = $('iteration-badge');
const timeline     = $('timeline');
const twinEntities = $('twin-entities');
const unknownsList = $('unknowns-list');
const evidenceList = $('evidence-list');
const hypothesesCard = $('hypotheses-card');
const hypothesesGrid = $('hypotheses-grid');
const simulationCard = $('simulation-card');
const simulationTable= $('simulation-table');
const devilCard    = $('devil-card');
const challengesList = $('challenges-list');
const decisionSection = $('decision-section');
const evidenceDrawer  = $('evidence-drawer');
const drawerOverlay   = $('drawer-overlay');
const drawerContent   = $('drawer-content');
const headerStatus    = $('header-status');

// ── Drag and drop upload ───────────────────────────────────
['dragenter','dragover'].forEach(evt =>
  dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.add('dragover'); })
);
['dragleave','drop'].forEach(evt =>
  dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.remove('dragover'); })
);
dropZone.addEventListener('drop', e => {
  const file = e.dataTransfer?.files?.[0];
  if (file) handleFile(file);
});
dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

async function handleFile(file) {
  showUploadStatus(`Uploading ${file.name}…`, '');
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch(`${API}/api/upload`, { method: 'POST', body: form });
    const data = await res.json();
    if (data.doc_id) {
      state.docId = data.doc_id;
      showUploadStatus(`✓ ${file.name} ingested (${data.chunks} chunks)`, 'success');
      enableStart();
    } else {
      showUploadStatus(`Error: ${data.detail || data.error || 'Upload failed'}`, 'error');
    }
  } catch (e) {
    showUploadStatus(`Network error: ${e.message}`, 'error');
  }
}

function showUploadStatus(msg, cls) {
  uploadStatus.className = `upload-status ${cls}`;
  uploadStatus.textContent = msg;
  uploadStatus.classList.remove('hidden');
}

// Enable start when question is typed
questionInput.addEventListener('input', enableStart);

function enableStart() {
  startBtn.disabled = !(questionInput.value.trim().length > 10);
}

// ── Start analysis ─────────────────────────────────────────
startBtn.addEventListener('click', startAnalysis);

async function startAnalysis() {
  const question = questionInput.value.trim();
  if (!question) return;

  startBtn.disabled = true;
  setStatus('active', 'Initialising…');

  // Switch to workspace
  setupPanel.classList.add('hidden');
  workspace.classList.remove('hidden');

  try {
    const res = await fetch(`${API}/api/case`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_id: state.docId, question, ...(window.getOperatingContext ? window.getOperatingContext() : {}) }),
    });
    const data = await res.json();
    if (res.ok && data.case_id) {
      state.caseId = data.case_id;
      subscribeToEvents(data.case_id);
    } else {
      const err = data.detail || data.error || 'Failed to create case';
      addTimelineEvent({ type: 'error', message: err });
      setStatus('error', err);
      startBtn.disabled = false;
    }
  } catch (e) {
    addTimelineEvent({ type: 'error', message: `Network error: ${e.message}` });
    setStatus('error', 'Network error');
    startBtn.disabled = false;
  }
}

// ── SSE Event streaming ────────────────────────────────────
function subscribeToEvents(caseId) {
  const es = new EventSource(`${API}/api/case/${caseId}/stream`);

  es.addEventListener('agent', evt => {
    try {
      const event = JSON.parse(evt.data);
      handleAgentEvent(event);
    } catch (e) {
      console.error('Event parse error', e);
    }
  });

  es.addEventListener('done', () => {
    es.close();
    setStatus('done', 'Analysis complete');
  });

  es.addEventListener('error', () => {
    es.close();
    setStatus('error', 'Connection lost');
  });

  es.onerror = () => {
    es.close();
    setStatus('error', 'Stream error');
  };
}

// ── Handle individual events ───────────────────────────────
function handleAgentEvent(event) {
  const type = event.type || 'unknown';

  // Update timeline
  addTimelineEvent(event);

  // Update iteration badge
  if (event.iteration !== undefined) {
    iterBadge.textContent = `Iteration ${event.iteration}`;
  }

  switch (type) {
    case 'agent_start':
      setStatus('active', `${event.agent}…`);
      break;

    case 'twin_update':
      renderEntityToSidebar(event);
      break;

    case 'agent_complete':
      if (event.unknowns) renderUnknowns(event.unknowns);
      if (event.superseded_ids && Array.isArray(event.superseded_ids)) {
        event.superseded_ids.forEach(id => {
          if (state.hypotheses[id]) state.hypotheses[id].status = 'superseded';
        });
        renderHypotheses();
      }
      if (event.hypothesis_id && state.hypotheses[event.hypothesis_id]) {
        if (event.hypothesis_status) state.hypotheses[event.hypothesis_id].status = event.hypothesis_status;
        if (event.hypothesis_confidence !== undefined) state.hypotheses[event.hypothesis_id].confidence = event.hypothesis_confidence;
        renderHypotheses();
      }
      break;

    case 'research_complete':
      if (event.evidence && Array.isArray(event.evidence)) {
        event.evidence.forEach(ev => addEvidenceItem(ev));
      }
      break;

    case 'hypothesis_created':
      state.hypotheses[event.hypothesis_id] = event;
      renderHypotheses();
      hypothesesCard.classList.remove('hidden');
      break;

    case 'simulation_result':
      state.simulations.push(event);
      // Update hypothesis confidence
      if (state.hypotheses[event.hypothesis_id]) {
        state.hypotheses[event.hypothesis_id].confidence = event.confidence;
      }
      renderSimulation();
      renderHypotheses();  // refresh confidence bars
      simulationCard.classList.remove('hidden');
      break;

    case 'challenge_raised':
      renderChallenge(event);
      devilCard.classList.remove('hidden');
      break;

    case 'workflow_complete':
      // Final result will come via the 'done' event
      break;

    case 'done':
      // The SSE adapter pushes the result inside the event
      if (event.result) {
        renderFinalDecision(event.result);
        renderEvidenceFromResult(event.result);
      }
      break;

    case 'error':
      setStatus('error', event.message || 'Error');
      break;
  }
}

// ── Timeline rendering ─────────────────────────────────────
function addTimelineEvent(event) {
  const type = event.type || 'unknown';
  const agentName = event.agent || event.node || '';
  const message   = event.message || '';

  // Build detail text
  let detail = '';
  if (event.query) detail += `Query: "${event.query}" `;
  if (event.weakness) detail += event.weakness;
  if (event.evidence_count) detail += `${event.evidence_count} evidence items`;
  if (event.hypothesis_count) detail += `${event.hypothesis_count} hypotheses`;
  if (event.verdict) detail += `Verdict: ${event.verdict}`;
  if (event.is_demo) detail += '<span class="event-demo-badge">DEMO DATA</span>';

  const el = document.createElement('div');
  el.className = `timeline-event ${type}`;
  el.innerHTML = `
    <div class="event-dot"></div>
    <div class="event-body">
      ${agentName ? `<div class="event-agent">${agentName}</div>` : ''}
      <div class="event-message">${escHtml(message)}</div>
      ${detail ? `<div class="event-detail">${detail}</div>` : ''}
    </div>`;
  timeline.appendChild(el);
  timeline.scrollTop = timeline.scrollHeight;
}

// ── Sidebar: Twin entities ─────────────────────────────────
const ENTITY_ICONS = {
  Company: '🏢', Product: '📦', CustomerSegment: '👥',
  Competitor: '⚔️', Market: '🌐', Constraint: '🔒', Objective: '🎯',
};

function renderEntityToSidebar(event) {
  const icon = ENTITY_ICONS[event.entity_type] || '◆';
  const attrs = event.attributes || {};
  const attrText = Object.entries(attrs)
    .filter(([k, v]) => v !== null && v !== undefined && k !== 'name')
    .slice(0, 3)
    .map(([k, v]) => `${k}: ${v}`)
    .join(' · ');

  const el = document.createElement('div');
  el.className = 'twin-entity';
  el.innerHTML = `
    <span class="entity-icon">${icon}</span>
    <div class="entity-body">
      <div class="entity-name">${escHtml(event.name)}</div>
      <div class="entity-type">${event.entity_type}</div>
      ${attrText ? `<div class="entity-attrs">${escHtml(attrText)}</div>` : ''}
    </div>`;
  twinEntities.appendChild(el);
}

function renderUnknowns(unknowns) {
  unknownsList.innerHTML = '';
  unknowns.forEach(u => {
    const li = document.createElement('li');
    li.textContent = u;
    unknownsList.appendChild(li);
  });
}

// ── Evidence sidebar ───────────────────────────────────────
function addEvidenceItem(ev) {
  if (!ev || !ev.id || state.evidence[ev.id]) return;
  state.evidence[ev.id] = ev;
  const el = document.createElement('div');
  el.className = 'evidence-item';
  el.innerHTML = `
    <div class="evidence-excerpt">${escHtml(ev.excerpt.substring(0, 100))}…</div>
    <div class="evidence-source">
      <span class="source-badge ${ev.source_type}">${ev.source_type}</span>
      <span>${escHtml(ev.source.substring(0, 40))}</span>
    </div>`;
  el.addEventListener('click', () => openDrawer(ev));
  evidenceList.appendChild(el);
}

function renderEvidenceFromResult(result) {
  const evArr = result.evidence || [];
  evidenceList.innerHTML = '';
  state.evidence = {};
  evArr.forEach(ev => addEvidenceItem(ev));
}

function openDrawer(ev) {
  drawerContent.innerHTML = `
    <p><strong>Source:</strong> ${escHtml(ev.source)}</p>
    <p><strong>Type:</strong> ${ev.source_type}</p>
    <p><strong>Epistemic status:</strong> ${ev.epistemic}</p>
    <hr style="border:none;border-top:1px solid var(--border);margin:0.75rem 0"/>
    <p>${escHtml(ev.excerpt)}</p>`;
  evidenceDrawer.classList.remove('hidden');
  evidenceDrawer.classList.add('open');
  drawerOverlay.classList.remove('hidden');
}

$('drawer-close').addEventListener('click', closeDrawer);
drawerOverlay.addEventListener('click', closeDrawer);

function closeDrawer() {
  evidenceDrawer.classList.remove('open');
  evidenceDrawer.classList.add('hidden');
  drawerOverlay.classList.add('hidden');
}

// ── Hypotheses ─────────────────────────────────────────────
function renderHypotheses() {
  hypothesesGrid.innerHTML = '';
  const hyps = Object.values(state.hypotheses).filter(h => h.status !== 'superseded');
  // Sort by confidence desc
  hyps.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
  hyps.forEach((h, idx) => {
    const conf = Math.round((h.confidence || 0.5) * 100);
    const rank = idx + 1;
    const el = document.createElement('div');
    el.className = `hypothesis-card rank-${rank} ${h.status === 'weakened' ? 'weakened' : ''}`;
    el.innerHTML = `
      <div class="hyp-title">${escHtml(h.title)}</div>
      <div class="hyp-price">₹${h.price || '?'}</div>
      <div class="hyp-channel">${escHtml(h.channel || '')} · ${escHtml(h.segment || '')}</div>
      <div class="hyp-confidence-bar-bg">
        <div class="hyp-confidence-bar" style="width:${conf}%"></div>
      </div>
      <div class="hyp-confidence-label">${conf}% confidence</div>
      ${h.status === 'weakened' ? '<div class="hyp-status weakened">⚠ Weakened</div>' : '<div class="hyp-status active">Active</div>'}`;
    hypothesesGrid.appendChild(el);
  });
}

// ── Simulation table ───────────────────────────────────────
function renderSimulation() {
  if (!state.simulations.length) return;
  const sorted = [...state.simulations].sort((a, b) => b.avg_profit - a.avg_profit);
  simulationTable.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Hypothesis</th>
          <th>Price</th>
          <th>Channel</th>
          <th>Avg Profit</th>
          <th>P(profit&gt;0)</th>
          <th>P10 / P90</th>
          <th>Demand/mo</th>
        </tr>
      </thead>
      <tbody>
        ${sorted.map(s => {
          const hyp = state.hypotheses[s.hypothesis_id];
          const title = hyp ? escHtml(hyp.title) : s.hypothesis_id;
          const profitCls = s.avg_profit >= 0 ? 'sim-positive' : 'sim-negative';
          const probPct = Math.round(s.prob_positive * 100);
          return `<tr>
            <td><strong>${title}</strong></td>
            <td>₹${s.price}</td>
            <td>${s.channel}</td>
            <td class="${profitCls}">₹${fmt(s.avg_profit)}</td>
            <td>
              <div class="prob-bar-container">
                <div class="prob-bar-bg"><div class="prob-bar" style="width:${probPct}%"></div></div>
                <span>${probPct}%</span>
              </div>
            </td>
            <td style="font-family:var(--font-mono);font-size:0.75rem">₹${fmt(s.p10)} / ₹${fmt(s.p90)}</td>
            <td>${fmt(s.avg_demand)}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
}

// ── Challenges ─────────────────────────────────────────────
function renderChallenge(event) {
  const el = document.createElement('div');
  el.className = `challenge-item ${event.severity}`;
  el.innerHTML = `
    <div class="challenge-severity ${event.severity}">[${event.severity}]</div>
    <div class="challenge-weakness">${escHtml(event.weakness || event.message)}</div>
    ${event.assumption ? `<div class="challenge-assumption">Targets assumption: ${escHtml(event.assumption)}</div>` : ''}`;
  challengesList.appendChild(el);
}

// ── Final Decision ─────────────────────────────────────────
function renderFinalDecision(result) {
  if (!result || result.error) {
    addTimelineEvent({ type: 'error', message: result?.error || 'No result' });
    return;
  }

  const conf = Math.round((result.confidence || 0.5) * 100);
  $('decision-recommendation').innerHTML = `
    <div class="rec-label">Recommendation</div>
    <div class="rec-text">${escHtml(result.recommendation)}</div>
    <div class="rec-rationale">${escHtml(result.rationale || '')}</div>
    <div class="rec-confidence">
      <span class="conf-label">Confidence</span>
      <div class="conf-bar-bg"><div class="conf-bar" style="width:${conf}%"></div></div>
      <span class="conf-pct">${conf}%</span>
    </div>`;

  $('decision-meta').textContent =
    `${result.total_iterations} iterations · ${result.research_calls} research calls · ${result.llm_calls} LLM calls`;

  renderList('supporting-ev', result.supporting_evidence || []);
  renderList('counter-ev', result.counter_evidence || []);
  renderList('assumptions-list', result.key_assumptions || []);
  renderList('change-list', result.what_would_change || []);
  renderList('risks-list', result.risks || []);
  renderList('bias-list', result.bias_disclosures || []);
  renderList('open-questions-list', result.open_questions || []);

  if (result.recommended_experiment) {
    $('experiment-box').innerHTML = `
      <div class="experiment-label">🧪 Recommended Experiment</div>
      <div class="experiment-text">${escHtml(result.recommended_experiment)}</div>`;
  }

  if (result.evolution_narrative) {
    $('evolution-box').innerHTML = `
      <div class="evolution-label">📈 How the Analysis Evolved</div>
      <div class="evolution-text">${escHtml(result.evolution_narrative)}</div>`;
  }

  if (result.open_questions?.length) {
    $('open-questions-box').innerHTML = `
      <h3>Open Questions</h3>
      <ul class="tagged-list">
        ${result.open_questions.map(q => `<li>${escHtml(q)}</li>`).join('')}
      </ul>`;
  }

  decisionSection.classList.remove('hidden');
  decisionSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderList(id, items) {
  const el = $(id);
  if (!el) return;
  el.innerHTML = items.map(i => `<li>${escHtml(i)}</li>`).join('');
}

// ── Status helpers ─────────────────────────────────────────
function setStatus(cls, text) {
  statusDot.className = `pulse ${cls}`;
  statusText.textContent = text;
}

// ── Utilities ──────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fmt(n) {
  if (n === null || n === undefined || isNaN(n)) return '?';
  return Math.round(n).toLocaleString('en-IN');
}
