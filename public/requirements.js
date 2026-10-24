/* Start-screen requirements guide + operating context (country/currency/tax).
   Data comes from /api/requirements and /api/jurisdictions. Default home market: USA. */
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let jurisdictions = [];

  async function loadGuide() {
    try {
      const g = await (await fetch('/api/requirements')).json();
      $('req-items').innerHTML = g.items.map(i => `
        <details class="req-item ${i.critical ? 'is-required' : ''}" data-id="${esc(i.id)}">
          <summary>
            <span class="req-badge ${i.critical ? 'req' : 'opt'}">${i.critical ? 'Required' : 'Helpful'}</span>
            <span class="req-name">${esc(i.title)}</span>
            <span class="req-state" data-state-for="${esc(i.id)}"></span>
          </summary>
          <p>${esc(i.why)}</p>
          <p class="req-ex"><strong>Example:</strong> ${esc(i.example)}</p>
          <p class="req-blocks"><strong>Without it:</strong> ${esc(i.blocks)}</p>
        </details>`).join('');
      $('req-tips').innerHTML = g.formats.tips.map(t => `<li>${esc(t)}</li>`).join('') +
        `<li>Supported files: ${esc(g.formats.supported.join(', '))}.</li><li>${esc(g.default_note)}</li>`;
    } catch (e) {
      $('req-items').textContent = 'Could not load the checklist: ' + e.message;
    }
  }

  function updateHint() {
    const code = $('ctx-country').value;
    const j = jurisdictions.find(x => x.code === code);
    if (!j) return;
    if (j.currency && !$('ctx-currency').dataset.touched) $('ctx-currency').placeholder = j.currency;
    const basis = $('ctx-tax-basis').value || j.typical_basis;
    const defaulted = !$('ctx-tax-basis').value;
    $('ctx-hint').textContent =
      `${j.tax_regime}. ${j.note} Using price basis: ${basis}${defaulted ? ' (country default — please confirm)' : ''}. ` +
      `No tax rate is assumed; add your rate in the notes if it matters.`;
  }

  async function loadJurisdictions() {
    try {
      const d = await (await fetch('/api/jurisdictions')).json();
      jurisdictions = d.jurisdictions;
      $('ctx-country').innerHTML = jurisdictions.map(j =>
        `<option value="${esc(j.code)}" ${j.code === d.default ? 'selected' : ''}>${esc(j.name)}${j.currency ? ' — ' + esc(j.currency) : ''}</option>`).join('');
      updateHint();
    } catch (e) {
      $('ctx-hint').textContent = 'Could not load countries: ' + e.message;
    }
  }

  // Exposed for main.js: only user-chosen values are sent; blanks stay defaulted server-side.
  window.getOperatingContext = function () {
    const v = id => $(id).value.trim();
    return { country: v('ctx-country') || null, currency: v('ctx-currency') || null,
             tax_basis: v('ctx-tax-basis') || null, tax_notes: v('ctx-tax-notes') || null };
  };

  let timer;
  async function liveScan() {
    const text = $('question-input').value;
    if (text.trim().length < 10) { $('req-live').textContent = ''; return; }
    try {
      const r = await (await fetch('/api/requirements/check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })).json();
      document.querySelectorAll('[data-state-for]').forEach(el => el.textContent = '');
      r.items.forEach(i => {
        const el = document.querySelector(`[data-state-for="${i.id}"]`);
        if (el) el.textContent = i.possibly_mentioned ? '✓ mentioned' : (i.critical ? '⚠ not found' : '');
      });
      const n = r.possibly_missing_critical.length;
      $('req-live').textContent = n
        ? `${n} required item(s) not detected in this text (keyword check; upload a document or add details). Missing items become UNKNOWN and may block a definitive answer.`
        : 'All required items appear to be mentioned (keyword check only; not verified).';
    } catch (_) { /* optional helper; ignore */ }
  }

  document.addEventListener('DOMContentLoaded', () => {});
  $('ctx-country').addEventListener('change', updateHint);
  $('ctx-tax-basis').addEventListener('change', updateHint);
  $('ctx-currency').addEventListener('input', e => { e.target.dataset.touched = '1'; e.target.value = e.target.value.toUpperCase(); });
  $('question-input').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(liveScan, 500); });
  loadGuide();
  loadJurisdictions();
})();
