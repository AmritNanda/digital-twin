import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { api } from './api';
import { planUpload } from './upload';
import type { CaseRecord, DecisionResult, EventRecord, RunRecord, Simulation, User } from './types';

type UploadItem = { name: string; status: 'uploading' | 'ready' | 'error'; detail?: string };
type Proposal = { overrides: Record<string, number>; baseRunId: string };

const money = (value?: number) => value === undefined ? '—' : new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value);
type EvidenceItem = NonNullable<DecisionResult['evidence']>[number];
const sourceLabel = (source?: string) => {
  if (!source) return 'Source';
  try {
    const host = new URL(source).hostname.toLowerCase().replace(/^www\./, '');
    const brands: Record<string, string> = {
      'cnbc.com': 'CNBC',
      'finance.yahoo.com': 'Yahoo Finance',
      'yahoo.com': 'Yahoo',
      'futuremarketinsights.com': 'Future Market Insights',
      'factmr.com': 'Fact.MR',
    };
    return brands[host] || host;
  } catch {
    return source.startsWith('document:') ? 'Company document' : source || 'Source';
  }
};
const sourceHref = (source?: string) => {
  if (!source) return undefined;
  try {
    const url = new URL(source);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
};
const readableMessage = (content: string, evidence: EvidenceItem[] = []): ReactNode => {
  const normalized = content.replace(/\bRun\s+(\d+)\s*[·|]\s*[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/gi, 'Run $1');
  const byId = new Map(evidence.map(item => [item.id.toLowerCase(), item]));
  const parts: ReactNode[] = [];
  const citationPattern = /\[([0-9a-f]{8})\]/gi;
  let cursor = 0;
  for (const match of normalized.matchAll(citationPattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(normalized.slice(cursor, index));
    const item = byId.get(match[1].toLowerCase());
    const label = item ? sourceLabel(item.source) : 'Source';
    const href = item ? sourceHref(item.source) : undefined;
    parts.push(href
      ? <a className="source-citation" href={href} target="_blank" rel="noreferrer" key={`${index}-${match[1]}`}>{label}</a>
      : <span className="source-citation" key={`${index}-${match[1]}`}>{label}</span>);
    cursor = index + match[0].length;
  }
  if (cursor < normalized.length) parts.push(normalized.slice(cursor));
  return parts;
};
const statusLabel = (status: string) => ({ draft: 'Draft', preparing_source: 'Reading documents', awaiting_question: 'Decision needed', running: 'Working', awaiting_approval: 'Review needed', completed: 'Complete', failed: 'Failed', rejected: 'Review declined', source_changed: 'Source changed' }[status] || status);
const eventLabel = (event: EventRecord) => {
  if (event.type === 'stage_record') return event.stage?.replaceAll('_', ' ') || 'Completed step';
  if (event.type === 'document_indexed') return `${event.filename} indexed`;
  if (event.type === 'approval_required') return 'Assumption review needed';
  if (event.type === 'source_twin_extracted') return 'Company source mapped';
  if (event.type === 'source_twin_deferred') return 'Documents indexed; source extraction deferred';
  if (event.type === 'case_completed') return 'Decision run completed';
  if (event.type === 'scenario_confirmed') return 'Scenario confirmed';
  if (event.type === 'analysis_started') return 'Analysis started';
  return event.message || event.type.replaceAll('_', ' ');
};
const showEvent = (event: EventRecord) => new Set(['stage_record', 'document_indexed', 'approval_required', 'source_twin_extracted', 'source_twin_deferred', 'source_preparation_started', 'source_corrected', 'challenge_raised', 'research_result', 'assumptions_approved', 'scenario_proposed', 'case_completed', 'scenario_confirmed', 'analysis_started', 'error']).has(event.type);

export default function App() {
  const reducedMotion = useReducedMotion();
  const fileInput = useRef<HTMLInputElement>(null);
  const [user, setUser] = useState<User | null>(null);
  const [caseData, setCaseData] = useState<CaseRecord | null>(null);
  const [phase, setPhase] = useState<'home' | 'dividing' | 'workbench'>('home');
  const [question, setQuestion] = useState('');
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [pendingStart, setPendingStart] = useState(false);
  const [pendingPicker, setPendingPicker] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [editingEntity, setEditingEntity] = useState('');
  const [correctionField, setCorrectionField] = useState('');
  const [correctionValue, setCorrectionValue] = useState('');
  const [correctionReason, setCorrectionReason] = useState('');
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [approvalValues, setApprovalValues] = useState<Record<string, number>>({});
  const [chatText, setChatText] = useState('');
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [chatPending, setChatPending] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async (id: string) => {
    const next = await api.case(id);
    setCaseData(next);
    return next;
  }, []);

  useEffect(() => {
    let alive = true;
    api.me().then(async account => {
      if (!alive) return;
      setUser(account);
      const id = localStorage.getItem('strategy_case_id');
      if (id) {
        try { const saved = await api.case(id); if (alive) { setCaseData(saved); setPhase(saved.status === 'draft' ? 'home' : 'workbench'); } }
        catch { localStorage.removeItem('strategy_case_id'); }
      }
    }).catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (caseData?.status === 'awaiting_approval' && caseData.approval.values) {
      setApprovalValues(caseData.approval.values);
    }
  }, [caseData?.status, caseData?.approval]);

  useEffect(() => {
    if (!caseData || !['running', 'preparing_source'].includes(caseData.status)) return;
    const id = caseData.id;
    const lastId = Math.max(0, ...caseData.events.map(event => event.id));
    const stream = new EventSource(`/api/cases/${id}/events?after=${lastId}`);
    stream.addEventListener('ledger', message => {
      const event = JSON.parse((message as MessageEvent).data) as EventRecord;
      setCaseData(previous => previous && previous.id === id
        ? { ...previous, events: previous.events.some(item => item.id === event.id) ? previous.events : [...previous.events, event] }
        : previous);
      if (['approval_required', 'case_completed', 'error'].includes(event.type)) refresh(id).catch(() => {});
    });
    stream.addEventListener('settled', () => { stream.close(); refresh(id).catch(() => {}); });
    return () => stream.close();
  }, [caseData?.id, caseData?.status, refresh]);

  const ensureCase = async (knownId?: string) => {
    if (knownId) return knownId;
    if (caseData?.id && ['draft', 'awaiting_question'].includes(caseData.status)) return caseData.id;
    const created = await api.createCase();
    setCaseData(created);
    localStorage.setItem('strategy_case_id', created.id);
    return created.id;
  };

  const uploadFiles = async (files: File[], knownId?: string) => {
    const plan = planUpload(files, (caseData?.documents || []).map(doc => ({ name: doc.filename, size: doc.size })));
    if (plan.error) {
      setError(plan.error);
      return knownId;
    }
    setUploadItems(items => [...items, ...plan.rejected.map(({ file, reason }) =>
      ({ name: file.name, status: 'error' as const, detail: reason }))]);
    if (!plan.accepted.length) return knownId;
    setUploading(true); setError('');
    let id = knownId;
    try {
      id = await ensureCase(knownId);
      for (const file of plan.accepted) {
        setUploadItems(items => [...items, { name: file.name, status: 'uploading' }]);
        try {
          await api.upload(id, file);
          setUploadItems(items => items.map(item => item.name === file.name && item.status === 'uploading' ? { ...item, status: 'ready' } : item));
          await refresh(id);
        } catch (cause) {
          const detail = cause instanceof Error ? cause.message : 'Upload failed';
          setUploadItems(items => items.map(item => item.name === file.name && item.status === 'uploading' ? { ...item, status: 'error', detail } : item));
        }
      }
    } finally { setUploading(false); }
    return id;
  };

  const acceptFiles = (files: File[]) => {
    if (!files.length) return;
    if (!user) { setPendingFiles(files); setLoginOpen(true); return; }
    uploadFiles(files).catch(cause => setError(String(cause)));
  };

  const start = async (knownId?: string, authenticated = false) => {
    if (busy || uploading) return;
    if (!user && !authenticated) { setPendingStart(true); setLoginOpen(true); return; }
    setBusy(true); setError('');
    try {
      const id = await ensureCase(knownId);
      const saved = await api.start(id, question.trim());
      setCaseData(saved);
      if (phase === 'home') {
        if (reducedMotion) setPhase('workbench');
        else { setPhase('dividing'); window.setTimeout(() => setPhase('workbench'), 820); }
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not start case'); }
    finally { setBusy(false); }
  };

  const signIn = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const account = await api.login(email, password);
      setUser(account); setLoginOpen(false); setPassword('');
      let id: string | undefined;
      if (pendingFiles.length) { id = await uploadFiles(pendingFiles); setPendingFiles([]); }
      if (pendingPicker) { setPendingPicker(false); fileInput.current?.click(); }
      if (pendingStart) { setPendingStart(false); await start(id, true); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Sign-in failed'); }
    finally { setBusy(false); }
  };

  const uploadClick = () => {
    if (!user) { setPendingPicker(true); setLoginOpen(true); return; }
    fileInput.current?.click();
  };

  const removeDocument = async (docId: string) => {
    if (!caseData) return;
    try { await api.removeDocument(caseData.id, docId); await refresh(caseData.id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not remove document'); }
  };

  const saveCorrection = async () => {
    if (!caseData || !editingEntity || !correctionField.trim() || !correctionReason.trim()) return;
    setBusy(true); setError('');
    try {
      setCaseData(await api.correctSource(caseData.id, editingEntity, correctionField.trim(), correctionValue.trim(), correctionReason.trim()));
      setEditingEntity(''); setCorrectionField(''); setCorrectionValue(''); setCorrectionReason('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save correction'); }
    finally { setBusy(false); }
  };

  const approve = async () => {
    if (!caseData) return;
    setBusy(true); setError('');
    try { setCaseData(await api.approve(caseData.id, approvalValues)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Approval failed'); }
    finally { setBusy(false); }
  };

  const sendChat = async () => {
    if (!caseData || !chatText.trim() || busy) return;
    setBusy(true); setChatPending(true); setError('');
    try {
      const response = await api.message(caseData.id, chatText.trim(), selectedRun?.id);
      setChatText(''); await refresh(caseData.id);
      if (response.type === 'scenario_proposal' && response.overrides && response.base_run_id) {
        setProposal({ overrides: response.overrides, baseRunId: response.base_run_id });
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not send message'); }
    finally { setBusy(false); setChatPending(false); }
  };

  const confirmScenario = async () => {
    if (!caseData || !proposal) return;
    setBusy(true); setError('');
    try {
      await api.scenario(caseData.id, proposal.baseRunId, proposal.overrides);
      setProposal(null); await refresh(caseData.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not create scenario'); }
    finally { setBusy(false); }
  };

  const displayedEvents = useMemo(() => (caseData?.events || []).filter(showEvent), [caseData?.events]);
  const selectedEvent = displayedEvents.find(event => event.id === selectedEventId) || displayedEvents.at(-1);
  const completedRuns = (caseData?.runs || []).filter(run => run.status === 'completed');
  const selectedRun: RunRecord | undefined = completedRuns.find(run => run.id === selectedRunId) || completedRuns.at(-1);
  const ledgerFocused = ['running', 'preparing_source', 'awaiting_approval'].includes(caseData?.status || '');
  const result = ledgerFocused ? undefined : selectedRun?.result;
  const maxProfitMagnitude = Math.max(1, ...(result?.simulations || []).map(sim => Math.abs(sim.avg_profit)));
  const provisionalTwin = caseData?.status === 'awaiting_approval'
    ? caseData.runs.at(-1)?.twin as { simulations?: Simulation[]; challenges?: { id: string; weakness: string; severity: string; assumption_targeted: string }[] } | undefined
    : undefined;

  const fileField = <input ref={fileInput} type="file" accept=".pdf,.docx,.csv,.txt,.md" multiple hidden
    onChange={event => { acceptFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />;

  return <div className="site" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); acceptFiles(Array.from(event.dataTransfer.files)); }}>
    {fileField}
    <header className="site-header"><button className="wordmark" type="button" onClick={() => { setPhase('home'); setCaseData(null); localStorage.removeItem('strategy_case_id'); }}><span className="brand-symbol">◈</span> Kairo</button><span className="header-subtitle">DECISION INTELLIGENCE</span><div className="header-right">{phase === 'workbench' && caseData && <button className="vault-button" type="button" onClick={() => setSourceOpen(true)}><span className="lock-glyph">▣</span> Private company twin <span className="mono">v{caseData.source_snapshot.version || 0}</span></button>}{user && <span className="account">{user.email}</span>}</div></header>

    <AnimatePresence mode="wait">
      {phase === 'home' && <motion.main key="home" className="home" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
        <div className="home-content"><p className="kicker">A DECISION STARTS WITH THE COMPANY</p><h1>Give your company a place to think.</h1><p className="home-copy">Bring the documents behind a decision. Kairo builds the case, tests competing paths, and shows what changed its mind.</p>
          <div className="composer home-composer"><textarea aria-label="Strategic question" value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); start(); } }} placeholder="What decision are you facing? You can add this after your documents." rows={3} /><div className="composer-actions"><button className="upload-primary" type="button" onClick={uploadClick}>＋ &nbsp; Upload company documents</button><span className="upload-limit">PDF · DOCX · CSV · TXT · MD &nbsp; / &nbsp; 5 files, 20 MB each, 50 MB total</span><button className="send-button" type="button" onClick={() => start()} disabled={busy || uploading} aria-label="Start decision">↗</button></div></div>
          {(caseData?.documents.length || uploadItems.length > 0) && <div className="file-list">{caseData?.documents.map(doc => <span className="file-chip" key={doc.id}>{doc.filename} <small>{doc.chunks} passages</small><button type="button" aria-label={`Remove ${doc.filename}`} onClick={() => removeDocument(doc.id)}>×</button></span>)}{uploadItems.filter(item => item.status !== 'ready').map((item, index) => <span className={`file-chip ${item.status}`} key={`${item.name}-${index}`}>{item.name} <small>{item.detail || item.status}</small></span>)}</div>}
          <p className="privacy-note"><span>▣</span> Your case is private to your account. Relevant excerpts may be processed by the configured language model provider.</p>
          <button className="text-path" type="button" onClick={() => { document.querySelector<HTMLTextAreaElement>('.home-composer textarea')?.focus(); }}>Or begin with text alone <span>↗</span></button>
        </div>
      </motion.main>}
      {phase === 'dividing' && <motion.main key="dividing" className="division" initial={{ opacity: 1 }} exit={{ opacity: 0 }} aria-label="Company source snapshot created; opening the decision workspace"><div className="division-label mono">SOURCE SNAPSHOT READY</div><div className="cell-pair"><motion.span className="cell source-cell" initial={{ x: 0, scale: 1 }} animate={{ x: 105, y: -28, scale: .64 }} transition={{ duration: .72, ease: [0.22, 1, 0.36, 1] }} /><motion.span className="cell working-cell" initial={{ x: 0, scale: 1 }} animate={{ x: -45, y: 18, scale: 1.65 }} transition={{ duration: .72, ease: [0.22, 1, 0.36, 1] }} /></div><div className="division-caption">Private source <span>↗</span> &nbsp;&nbsp; Working decision <span>↙</span></div></motion.main>}
      {phase === 'workbench' && caseData && <motion.main key="workbench" className="workbench" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <div className="case-heading"><div><div className="eyebrow">CASE {caseData.id.slice(0, 8).toUpperCase()} <span>/</span> SOURCE v{caseData.source_snapshot.version || 0}</div><h1>{caseData.question || 'Choose the decision to test.'}</h1></div><div className={`case-status ${caseData.status}`}><span className="status-dot" />{statusLabel(caseData.status)}</div></div>

        {caseData.status === 'source_changed' && <div className="source-changed"><div><strong>The company source has changed.</strong><p>The visible result uses source version {selectedRun?.result.source_version ?? 'earlier'}. Run the analysis again to use version {caseData.source_snapshot.version}.</p></div><button className="solid-action" type="button" disabled={busy} onClick={() => start(caseData.id)}>Analyze corrected source ↗</button></div>}

        {caseData.status === 'awaiting_question' && <section className="question-gate"><div className="eyebrow">SOURCE TWIN READY</div><h2>What decision should we test?</h2><p>The uploaded documents are indexed. Choose a question or write your own; simulations start only after you decide.</p><div className="suggestions">{caseData.source_snapshot.suggested_questions?.map(item => <button type="button" key={item} onClick={() => setQuestion(item)}>{item} ↗</button>)}</div><div className="composer"><textarea aria-label="Decision question" value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); start(); } }} placeholder="What decision should we test?" rows={2} /><div className="composer-actions"><span className="mono">ENTER TO ANALYZE · SHIFT+ENTER FOR NEW LINE</span><button className="send-button" type="button" onClick={() => start()} disabled={busy || question.trim().length < 10}>↗</button></div></div></section>}

        {caseData.status !== 'awaiting_question' && <div className={`workspace-grid ${ledgerFocused ? 'ledger-focused' : ''}`}><div className="workspace-primary">
          {result && <section className="decision-summary"><div className="section-top"><span className="eyebrow">DECISION / RUN {selectedRun?.version}</span><div className="run-actions"><select aria-label="Selected run version" value={selectedRun?.id || ''} onChange={event => setSelectedRunId(event.target.value)}>{completedRuns.map(run => <option key={run.id} value={run.id}>Run {run.version}</option>)}</select><div className="export-wrap"><button type="button" className="outline-action" onClick={() => setExportOpen(!exportOpen)}>Export ↓</button>{exportOpen && <div className="export-menu">{(['pdf', 'csv', 'json'] as const).map(format => <a key={format} href={`/api/cases/${caseData.id}/exports/${format}?run_id=${selectedRun?.id}`}>{format.toUpperCase()} <span>↗</span></a>)}</div>}</div></div></div><div className="recommendation-label">RECOMMENDED DIRECTION</div><p className="recommendation-copy">{result.recommendation || 'Decision ready'}</p>{result.rationale && <p className="rationale-copy">{result.rationale}</p>}{result.fixture_data_present && <span className="fixture-disclosure">FIXTURE / DEMO EVIDENCE IN THIS RUN</span>}</section>}

          {caseData.status === 'awaiting_approval' && <section className="approval-panel"><div className="eyebrow">HUMAN CHECKPOINT</div><h2>Review what the final run will assume.</h2><p>These are model inputs. Edit anything that should change, then approve the final simulation. The provisional run remains in the ledger.</p><div className="assumption-grid">{Object.entries(approvalValues).map(([key, value]) => <label key={key}><span>{key.replaceAll('_', ' ').replace(' inr', ' · INR')}</span><input type="number" step={key === 'elasticity' ? '.1' : '1'} value={value} onChange={event => setApprovalValues(previous => ({ ...previous, [key]: Number(event.target.value) }))} /></label>)}</div><button className="solid-action" type="button" onClick={approve} disabled={busy}>Approve & run final simulation ↗</button></section>}

          {provisionalTwin && <section className="results-block provisional"><div className="section-top"><h3>Provisional findings</h3><span className="eyebrow">BEFORE ASSUMPTION APPROVAL</span></div><p>These figures and challenges may change in the final run.</p>{provisionalTwin.simulations?.map(sim => <div className="provisional-row" key={sim.id || sim.hypothesis_id}><span>{sim.channel || sim.hypothesis_id}</span><strong>₹{money(sim.avg_profit)} expected</strong><small>P10 ₹{money(sim.p10_profit)} · P90 ₹{money(sim.p90_profit)}</small></div>)}{provisionalTwin.challenges?.map(item => <p key={item.id}><span className="eyebrow">{item.severity} / {item.assumption_targeted}</span><br />{item.weakness}</p>)}</section>}

          {!result && ['running', 'preparing_source'].includes(caseData.status) && <section className="working-status"><div className="eyebrow">{caseData.status === 'preparing_source' ? 'SOURCE PREPARATION' : 'ANALYSIS IN PROGRESS'}</div><h2>{caseData.status === 'preparing_source' ? 'Reading the company documents.' : 'Building the working twin.'}</h2><p>Each completed step appears in the ledger with its actual inputs and outputs.</p><div className="working-rule"><span /></div></section>}

          {result?.simulations && <section className="results-block"><div className="section-top"><h3>Profit outlook</h3><span className="eyebrow">EXPECTED MONTHLY PROFIT · INR</span></div><div className="profit-chart" role="img" aria-label="Expected monthly profit comparison; positive bars extend right and negative bars extend left from zero.">{[...result.simulations].sort((a, b) => b.avg_profit - a.avg_profit).map(sim => { const hypothesis = result.hypotheses?.find(item => item.id === sim.hypothesis_id); return <div className="profit-row" key={sim.hypothesis_id}><div className="profit-name"><strong>{hypothesis?.title || sim.channel || sim.hypothesis_id}</strong><small>{sim.price ? `₹${money(sim.price)}` : ''} {sim.channel}</small></div><div className="profit-track"><span className={`profit-bar ${sim.avg_profit >= 0 ? 'positive' : 'negative'}`} style={{ width: `${Math.abs(sim.avg_profit) / maxProfitMagnitude * 50}%` }} /></div><strong className="profit-value">₹{money(sim.avg_profit)}</strong></div>; })}<div className="profit-axis"><span>− lower profit</span><span>0</span><span>higher profit +</span></div></div></section>}

          {result?.simulations && <section className="results-block"><div className="section-top"><h3>Competing options</h3><span className="eyebrow">MONTHLY PROJECTION · INR</span></div><div className="table-scroll"><table><thead><tr><th>Option</th><th>Expected</th><th>P10</th><th>P50</th><th>P90</th><th>Profitable</th></tr></thead><tbody>{[...result.simulations].sort((a, b) => b.avg_profit - a.avg_profit).map(sim => { const hypothesis = result.hypotheses?.find(item => item.id === sim.hypothesis_id); return <tr key={sim.hypothesis_id}><td><strong>{hypothesis?.title || sim.channel || sim.hypothesis_id}</strong><small>{sim.price ? `₹${money(sim.price)}` : ''} {sim.channel}</small></td><td>₹{money(sim.avg_profit)}</td><td>₹{money(sim.p10_profit)}</td><td>₹{money(sim.p50_profit)}</td><td>₹{money(sim.p90_profit)}</td><td>{Math.round(sim.prob_positive * 100)}%</td></tr>; })}</tbody></table></div></section>}

          {result?.sensitivity && result.sensitivity.length > 0 && <section className="results-block"><div className="section-top"><h3>What changes the ranking?</h3><span className="eyebrow">ELASTICITY × ACQUISITION COST</span></div><div className="sensitivity-grid">{result.sensitivity.map((point, index) => <div className="sensitivity-point" key={index}><small>e {point.elasticity.toFixed(2)} / CAC ₹{money(point.cac_inr)}</small><strong>{result.hypotheses?.find(item => item.id === point.leader_hypothesis_id)?.title || point.leader_hypothesis_id}</strong><span>₹{money(point.leader_avg_profit)} expected</span></div>)}</div></section>}

          {result && <section className="results-block findings"><div><h3>Challenges & uncertainty</h3>{result.challenges?.length ? result.challenges.map(item => <p key={item.id}><span className="eyebrow">{item.severity} / {item.id}</span><br />{item.weakness}</p>) : <p>No recorded challenge in this run.</p>}{result.uncertainty_statement && <p>{result.uncertainty_statement}</p>}</div><div><h3>Evidence used</h3>{result.evidence?.length ? result.evidence.map(item => { const href = sourceHref(item.source); const label = sourceLabel(item.source); return <p key={item.id}><span className="eyebrow">{href ? <a className="source-citation" href={href} target="_blank" rel="noreferrer">{label}</a> : label} / {item.source_type}</span><br />{item.excerpt}</p>; }) : <p>No evidence attached.</p>}</div></section>}

          {result?.pilot && <section className="pilot"><div className="eyebrow">PROPOSED NEXT ACTION / REQUIRES APPROVAL</div><h3>Run a capped {result.pilot.duration_weeks}-week pilot.</h3><p>Budget cap: ₹{money(result.pilot.budget_cap_inr)}. Measure {result.pilot.measure.join(', ').toLowerCase()}.</p><p className="pilot-stop">STOP CONDITION · {result.pilot.stop_condition}</p></section>}

          {result && <section className="conversation"><div className="section-top"><h3>Discuss this decision</h3><span className="eyebrow">GROUNDED IN RUN {selectedRun?.version}</span></div>{caseData.messages.map(message => { const messageRun = completedRuns.find(run => run.id === message.run_id); return <div className={`message ${message.role}`} key={message.id}><span className="eyebrow">{message.role === 'user' ? 'YOU' : 'KAIRO'}</span><p>{readableMessage(message.content, messageRun?.result.evidence || [])}</p></div>; })}{chatPending && <div className="message assistant chat-thinking" role="status" aria-live="polite"><span className="eyebrow">KAIRO</span><p>Thinking through the report<span className="thinking-dots"><i /><i /><i /></span></p></div>}{proposal && <div className="proposal"><strong>New scenario proposed</strong><p>{Object.entries(proposal.overrides).map(([key, value]) => `${key}: ${value}`).join(' · ')}</p><button type="button" className="solid-action" onClick={confirmScenario} disabled={busy}>Confirm new run ↗</button><button type="button" className="quiet-action" onClick={() => setProposal(null)}>Dismiss</button></div>}<div className="composer chat-composer"><textarea aria-label="Discuss the decision" value={chatText} onChange={event => setChatText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendChat(); } }} placeholder="Ask why an option won, or propose a new assumption…" rows={2} /><div className="composer-actions"><span className="mono">CHANGES CREATE A NEW RUN</span><button className="send-button" type="button" onClick={sendChat} disabled={busy || !chatText.trim()} aria-label={chatPending ? 'Kairo is thinking' : 'Send message'}>{chatPending ? <span className="button-spinner" /> : '↗'}</button></div></div></section>}
        </div>
        <aside className="ledger"><div className="section-top"><h3>Run ledger</h3><span className="mono">{displayedEvents.length} RECORDS</span></div><div className="ledger-list">{displayedEvents.map(event => <button type="button" className={`ledger-event ${selectedEvent?.id === event.id ? 'selected' : ''}`} key={event.id} onClick={() => setSelectedEventId(event.id)}><span className="event-time mono">{new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span><span className="event-content"><strong>{eventLabel(event)}</strong><small>{event.stage || event.type} · {event.status || 'recorded'}</small></span></button>)}</div><div className="event-inspector"><div className="eyebrow">SELECTED RECORD / {selectedEvent?.id || '—'}</div>{selectedEvent ? <><h4>{eventLabel(selectedEvent)}</h4><p>{selectedEvent.message || selectedEvent.type.replaceAll('_', ' ')}</p>{Object.entries(selectedEvent).filter(([key]) => !['id', 'case_id', 'created_at', 'type', 'message', 'run_id'].includes(key)).map(([key, value]) => <div className="inspector-row" key={key}><span className="mono">{key.replaceAll('_', ' ')}</span><code>{typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}</code></div>)}</> : <p>Events will appear as the system works.</p>}</div></aside></div>}
      </motion.main>}
    </AnimatePresence>

    {error && <div className="error-bar" role="alert">{error}<button type="button" onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}

    {loginOpen && <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setLoginOpen(false); }}><form className="login-modal" onSubmit={signIn}><div className="eyebrow">PRIVATE WORKSPACE</div><h2>Sign in before uploading.</h2><p>Your documents are restricted to your account. Relevant excerpts may be sent to the configured language model provider for analysis.</p><label>Email<input type="email" autoComplete="username" value={email} onChange={event => setEmail(event.target.value)} required /></label><label>Password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label><button className="solid-action" type="submit" disabled={busy}>Sign in & continue ↗</button><button className="quiet-action" type="button" onClick={() => setLoginOpen(false)}>Cancel</button></form></div>}

    {sourceOpen && caseData && <div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setSourceOpen(false); }}><aside className="source-drawer"><div className="drawer-head"><div><div className="eyebrow">PRIVATE / SOURCE VERSION {caseData.source_snapshot.version || 0}</div><h2>Company twin</h2></div><button type="button" onClick={() => setSourceOpen(false)} aria-label="Close source twin">×</button></div><p className="drawer-intro">The source side records uploaded company information. Working runs are stored separately and retain their source version.</p><h3>Documents</h3>{caseData.documents.map(doc => <div className="source-item" key={doc.id}><strong>{doc.filename}</strong><small>{doc.chunks} indexed passages · {Math.ceil(doc.size / 1024)} KB</small>{['draft', 'awaiting_question'].includes(caseData.status) && <button type="button" onClick={() => removeDocument(doc.id)}>Remove</button>}</div>)}<h3>Extracted entities</h3>{caseData.source_snapshot.entities?.length ? caseData.source_snapshot.entities.map(entity => <div className="source-item" key={entity.id}><span className="eyebrow">{entity.type}</span><strong>{entity.name}</strong><small>{Object.entries(entity.attributes).slice(0, 4).map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}</small><button type="button" onClick={() => setEditingEntity(editingEntity === entity.id ? '' : entity.id)}>Correct a detail</button>{editingEntity === entity.id && <div className="correction-form"><select aria-label="Fact to correct" value={correctionField} onChange={event => { setCorrectionField(event.target.value); setCorrectionValue(String(entity.attributes[event.target.value] ?? '')); }}><option value="">Choose a field</option>{Object.keys(entity.attributes).map(field => <option key={field} value={field}>{field}</option>)}</select><input aria-label="Corrected value" value={correctionValue} onChange={event => setCorrectionValue(event.target.value)} placeholder="Correct value" /><input aria-label="Reason for correction" value={correctionReason} onChange={event => setCorrectionReason(event.target.value)} placeholder="Reason / source" /><button type="button" className="solid-action" disabled={busy || !correctionField || !correctionReason} onClick={saveCorrection}>Save new source version</button></div>}</div>) : <p>Entities will appear when document understanding completes.</p>}<h3>Company-reported facts & assumptions</h3>{caseData.source_snapshot.facts?.length ? caseData.source_snapshot.facts.map((fact, index) => <p className="source-unknown" key={`${fact.entity_id}-${fact.field}-${index}`}><span className="eyebrow">{fact.epistemic}</span> · {fact.field.replaceAll('_', ' ')}: {String(fact.value)}</p>) : <p className="source-unknown">Facts appear after extraction. Fields inferred by the model are marked separately from known values.</p>}<h3>Source passages used</h3>{caseData.source_snapshot.used_passages?.length ? caseData.source_snapshot.used_passages.map((passage, index) => <p className="source-unknown" key={`${passage.doc_id}-${index}`}><strong>{caseData.documents.find(doc => doc.id === passage.document_id)?.filename || passage.source}</strong> · {passage.doc_id}<br />{passage.excerpt}</p>) : <p className="source-unknown">No document passages were used in this extraction.</p>}<h3>Corrections</h3>{caseData.source_snapshot.corrections?.length ? caseData.source_snapshot.corrections.map((item, index) => <p className="source-unknown" key={index}>{item.entity_name} · {item.field}: {String(item.before)} → {String(item.value)}<br />{item.reason}</p>) : <p className="source-unknown">No owner corrections yet.</p>}<h3>Unresolved questions</h3>{caseData.source_snapshot.unknowns?.map((item, index) => <p className="source-unknown" key={index}>{item}</p>)}</aside></div>}
  </div>;
}
