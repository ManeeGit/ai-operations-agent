/* Local-only operations console. API strings are never interpreted as HTML. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = { overview: null, selectedId: null, filter: 'active', busy: false, loading: false, failures: 0, timer: null, toastTimer: null };
  const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
  const timeFormat = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const fullTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' });

  function node(tag, className, value) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (value !== undefined && value !== null) item.textContent = String(value);
    return item;
  }
  function values(value) { return Array.isArray(value) ? value : []; }
  function text(value, fallback = '—') { return value === undefined || value === null || value === '' ? fallback : String(value); }
  function numeric(value) { return value !== null && value !== '' && value !== undefined && Number.isFinite(Number(value)); }
  function formatNumber(value) { return numeric(value) ? numberFormat.format(Number(value)) : '—'; }
  function clock(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? timeFormat.format(date) : '—';
  }
  function timestamp(value) {
    const item = node('time', '', clock(value));
    const date = new Date(value);
    if (value && Number.isFinite(date.getTime())) { item.dateTime = date.toISOString(); item.title = fullTimeFormat.format(date); }
    return item;
  }
  function titleCase(value) { return text(value, 'Unknown').replace(/[_-]+/g, ' ').replace(/^./, (character) => character.toUpperCase()); }
  function badge(label, tone = 'neutral') { return node('span', `badge ${tone}`, label); }
  function severityTone(value) {
    return ['critical', 'high', 'error'].includes(String(value).toLowerCase()) ? 'red' : ['warning', 'medium', 'warn'].includes(String(value).toLowerCase()) ? 'amber' : 'neutral';
  }
  function isActive(incident) { return !['resolved', 'closed'].includes(String(incident.status).toLowerCase()); }
  function showToast(message) {
    $('toast').textContent = message;
    $('toast').hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5200);
  }
  function announce(message) { $('announcement').textContent = message; }
  function setConnection(ok) {
    const indicator = $('connection-state').querySelector('.status-dot');
    indicator.className = `status-dot ${ok ? 'mint' : 'amber'}`;
    $('connection-label').textContent = ok ? 'Agent connected' : 'Reconnecting';
  }
  function setBusy(busy) {
    state.busy = busy;
    document.querySelectorAll('[data-scenario]').forEach((button) => { button.disabled = busy || !state.overview?.csrf_token; });
    $('refresh-button').disabled = busy;
    const ack = $('ack-button');
    if (ack) ack.disabled = busy || !state.overview?.csrf_token;
    $('scenario-panel').setAttribute('aria-busy', String(busy));
  }
  function errorBanner(message, action = false) {
    $('error-title').textContent = action ? 'The action could not be completed' : 'Connection interrupted';
    $('error-message').textContent = message;
    $('error-banner').hidden = false;
    if (!action) setConnection(false);
  }
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.method === 'POST' ? 90000 : 12000);
    try {
      const response = await fetch(path, { ...options, signal: controller.signal, credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json', ...options.headers } });
      if (!response.ok) {
        const error = new Error(response.status === 403 ? 'The local session token changed. Refresh the console before trying again.' : `The agent returned HTTP ${response.status}.`);
        error.status = response.status;
        throw error;
      }
      const data = await response.json();
      return data;
    } finally { clearTimeout(timeout); }
  }
  function preserveFocus(render) {
    const active = document.activeElement;
    const focusKey = active?.getAttribute('data-focus-key');
    const id = active?.id;
    render();
    if (active && !document.contains(active)) {
      const replacement = id ? $(id) : focusKey ? Array.from(document.querySelectorAll('[data-focus-key]')).find((item) => item.getAttribute('data-focus-key') === focusKey) : null;
      replacement?.focus({ preventScroll: true });
    }
  }
  function renderOverview(data) {
    if (!data || typeof data !== 'object' || !Array.isArray(data.services) || !Array.isArray(data.incidents)) throw new Error('The agent returned an unexpected overview.');
    state.overview = data;
    state.failures = 0;
    setConnection(true);
    $('error-banner').hidden = true;
    $('last-updated').textContent = `Updated ${clock(data.generated_at)}`;
    $('mode-badge').textContent = data.mode === 'demo' ? 'SYNTHETIC DEMO' : 'MONITOR MODE';
    $('mode-badge').className = `badge ${data.mode === 'demo' ? 'amber' : 'mint'}`;
    $('scenario-panel').hidden = data.mode !== 'demo';
    $('monitor-note').hidden = data.mode === 'demo';
    const model = data.model || {};
    const modelEnabled = Boolean(model.enabled);
    $('engine-label').textContent = modelEnabled ? titleCase(model.provider || 'Ollama') : 'Local rules';
    $('engine-description').textContent = modelEnabled ? `${text(model.model, 'Configured model')} · evidence-grounded inference with rule fallback.` : 'Deterministic detection and runbook-based recommendations. No model required.';
    $('model-call-description').textContent = modelEnabled ? `${titleCase(model.provider || 'Ollama')} · ${text(model.model, 'local model')}` : 'Local-rule mode · no model required';
    $('privacy-copy').textContent = data.mode === 'demo' ? 'Demo telemetry is synthetic. This console has no third-party assets or analytics. Optional Ollama inference uses the fixed loopback endpoint.' : 'Telemetry is served by your agent. This console has no third-party assets or analytics. Optional Ollama inference uses the fixed loopback endpoint.';
    const stats = data.stats || {};
    $('stat-samples').textContent = formatNumber(stats.samples);
    $('stat-open').textContent = formatNumber(stats.incidents_open);
    $('stat-total-description').textContent = `${formatNumber(stats.incidents_total)} incidents recorded in total`;
    $('stat-model-calls').textContent = formatNumber(stats.model_calls);
    $('stat-model-failures').textContent = formatNumber(stats.model_failures);
    $('nav-incident-count').textContent = formatNumber(stats.incidents_open);
    $('service-count').textContent = String(data.services.length);
    preserveFocus(() => { renderServices(data.services); renderIncidents(); renderActivity(values(data.events)); });
    setBusy(state.busy);
  }
  function metric(label, value, unit, warning = false) {
    const block = node('div');
    block.append(node('p', 'metric-caption', label));
    const number = node('p', `metric-value${warning ? ' warning' : ''}`, formatNumber(value));
    if (numeric(value)) number.append(node('small', '', unit));
    block.append(number);
    return block;
  }
  function resource(label, value) {
    const block = node('div');
    const heading = node('div', 'resource-label');
    heading.append(node('span', '', label), node('span', '', numeric(value) ? `${formatNumber(value)}%` : '—'));
    const track = node('div', 'resource-track');
    const fill = node('div', `resource-fill${numeric(value) && Number(value) >= 80 ? ' warm' : ''}`);
    fill.style.width = `${numeric(value) ? Math.min(100, Math.max(0, Number(value))) : 0}%`;
    track.setAttribute('aria-hidden', 'true');
    track.append(fill);
    block.append(heading, track);
    return block;
  }
  function renderServices(services) {
    const root = $('services-grid');
    const fragment = document.createDocumentFragment();
    services.forEach((service) => {
      const status = ['healthy', 'degraded'].includes(service.status) ? service.status : 'unknown';
      const card = node('article', `service-card ${status}`);
      const header = node('div', 'service-header');
      const name = node('div', 'service-name-wrap');
      const symbol = node('span', 'service-symbol', '▱');
      symbol.setAttribute('aria-hidden', 'true');
      name.append(symbol, node('h3', '', text(service.name, 'Unnamed service')));
      header.append(name, badge(titleCase(status), status === 'healthy' ? 'mint' : status === 'degraded' ? 'amber' : 'neutral'));
      const metrics = node('div', 'service-metrics');
      metrics.append(metric('Response time', service.latency_ms, 'ms', numeric(service.latency_ms) && Number(service.latency_ms) >= 500), metric('Error rate', numeric(service.error_rate) ? Number(service.error_rate) * 100 : null, '%', numeric(service.error_rate) && Number(service.error_rate) >= .05));
      const resources = node('div', 'service-resources');
      resources.append(resource('CPU', service.cpu_pct), resource('Memory', service.memory_pct));
      const foot = node('div', 'service-time');
      const seen = node('span', '', 'LAST SEEN ');
      seen.append(timestamp(service.last_seen));
      foot.append(seen, node('span', '', 'LATEST SAMPLE'));
      card.append(header, metrics, resources, foot);
      fragment.append(card);
    });
    if (!services.length) {
      const empty = node('div', 'empty-state');
      empty.append(node('h3', '', 'No telemetry yet'), node('p', '', state.overview?.mode === 'demo' ? 'Choose a synthetic scenario above to add service samples.' : 'Waiting for the configured telemetry source.'));
      fragment.append(empty);
    }
    root.replaceChildren(fragment);
  }
  function renderIncidents() {
    const incidents = values(state.overview?.incidents);
    const filtered = state.filter === 'active' ? incidents.filter(isActive) : incidents;
    if (!filtered.some((incident) => String(incident.id) === state.selectedId)) state.selectedId = filtered.length ? String(filtered[0].id) : null;
    const fragment = document.createDocumentFragment();
    filtered.forEach((incident) => {
      const button = node('button', `incident-item${String(incident.id) === state.selectedId ? ' selected' : ''}`);
      button.type = 'button';
      button.setAttribute('data-focus-key', `incident-${incident.id}`);
      button.setAttribute('aria-pressed', String(String(incident.id) === state.selectedId));
      button.setAttribute('aria-controls', 'incident-detail');
      const top = node('div', 'incident-item-top');
      top.append(node('span', 'incident-service', text(incident.service)), badge(titleCase(incident.severity), severityTone(incident.severity)));
      const bottom = node('div', 'incident-meta');
      bottom.append(node('span', '', titleCase(incident.status)), timestamp(incident.updated_at || incident.opened_at));
      button.append(top, node('h4', '', text(incident.title, titleCase(incident.kind))), bottom);
      button.addEventListener('click', () => { state.selectedId = String(incident.id); preserveFocus(renderIncidents); announce(`Selected incident: ${text(incident.title)}`); });
      fragment.append(button);
    });
    if (!filtered.length) {
      const empty = node('div', 'queue-empty');
      empty.append(node('span', '', '◎'), node('p', '', state.filter === 'active' ? 'No active incidents' : 'No incidents recorded'), node('small', '', state.filter === 'active' && incidents.length ? 'Select All to review earlier incidents.' : 'New detections will appear here.'));
      fragment.append(empty);
    }
    $('incident-list').replaceChildren(fragment);
    const selected = incidents.find((incident) => String(incident.id) === state.selectedId);
    renderDetail(selected);
  }
  function detailSection(label, count) {
    const heading = node('h3', 'detail-section-title', label);
    if (count !== undefined) heading.append(node('span', '', count));
    return heading;
  }
  function renderDetail(incident) {
    const root = $('incident-detail');
    root.replaceChildren();
    if (!incident) {
      const empty = node('div', 'detail-empty');
      const orbit = node('div', 'empty-orbit');
      orbit.setAttribute('aria-hidden', 'true');
      orbit.append(node('span', '', '◎'));
      empty.append(orbit, node('p', 'eyebrow', 'EVIDENCE BEFORE ACTION'), node('h3', '', 'Quiet is a good signal.'), node('p', '', state.overview?.mode === 'demo' ? 'No active incident selected. Generate a demo scenario to explore detection, diagnosis, and human-reviewed next steps.' : 'No incident selected. The agent is waiting for an actionable signal.'));
      root.append(empty);
      return;
    }
    const top = node('div', 'detail-topline');
    const badges = node('div', 'detail-badges');
    badges.append(badge(titleCase(incident.severity), severityTone(incident.severity)), badge(titleCase(incident.status)), badge(text(incident.service)));
    top.append(badges, node('span', 'incident-id', text(incident.id)));
    const meta = node('div', 'detail-meta');
    const opened = node('span', '', 'Opened ');
    opened.append(timestamp(incident.opened_at));
    meta.append(opened, node('span', '', `${formatNumber(incident.occurrences)} occurrences`), node('span', '', titleCase(incident.kind)));
    const controls = node('div', 'detail-controls');
    controls.append(node('p', '', 'Acknowledgement updates this local incident only. It does not resolve the underlying signal.'));
    const acknowledged = ['acknowledged', 'acked', 'ack'].includes(String(incident.status).toLowerCase());
    if (isActive(incident) && !acknowledged) {
      const button = node('button', 'button button-primary', 'Acknowledge incident');
      button.id = 'ack-button';
      button.type = 'button';
      button.disabled = state.busy || !state.overview?.csrf_token;
      button.addEventListener('click', () => acknowledge(incident.id));
      controls.append(button);
    } else controls.append(badge(acknowledged ? 'Acknowledged locally' : titleCase(incident.status), 'mint'));
    root.append(top, node('h2', 'detail-title', text(incident.title, titleCase(incident.kind))), meta, controls);
    const diagnosis = incident.diagnosis || {};
    const box = node('div', 'diagnosis-box');
    const diagnosisTop = node('div', 'diagnosis-top');
    const source = String(diagnosis.source || 'local rules');
    const label = node('div', 'diagnosis-label');
    label.append(node('span', '', '✧'), node('strong', '', `${titleCase(source)} diagnosis`));
    const confidence = numeric(diagnosis.confidence) ? `${formatNumber(Number(diagnosis.confidence) <= 1 ? Number(diagnosis.confidence) * 100 : Number(diagnosis.confidence))}% confidence` : `${text(diagnosis.confidence, 'Unrated')} confidence`;
    diagnosisTop.append(label, node('span', 'confidence-label', confidence));
    box.append(diagnosisTop, node('p', '', text(diagnosis.summary, 'Diagnosis is not yet available. Review the observed signals below.')));
    box.append(node('p', 'uncertainty', `Uncertainty: ${text(diagnosis.uncertainty, 'This is a hypothesis based on the available telemetry, not a verified root cause.')}`));
    root.append(box);
    const signals = values(incident.signals);
    root.append(detailSection('Detected signals', signals.length));
    const signalList = node('div', 'signals-list');
    signals.forEach((signal) => {
      const row = node('div', 'signal-row');
      row.append(node('span', 'signal-name', titleCase(signal.name)), node('span', 'signal-number', text(signal.value)), node('p', 'signal-explanation', text(signal.explanation, 'No additional explanation supplied.')));
      const details = [];
      if (signal.baseline !== undefined && signal.baseline !== null) details.push(`Baseline: ${text(signal.baseline)}`);
      if (signal.threshold !== undefined && signal.threshold !== null) details.push(`Threshold: ${text(signal.threshold)}`);
      if (details.length) row.append(node('p', 'signal-baseline', details.join('  ·  ')));
      signalList.append(row);
    });
    if (!signals.length) signalList.append(node('p', 'no-data', 'No structured signal details recorded.'));
    root.append(signalList);
    const steps = values(diagnosis.next_steps);
    root.append(detailSection('Suggested next steps', steps.length));
    const stepList = node('ol', 'steps-list');
    steps.forEach((step) => {
      const item = node('li', 'step');
      const footer = node('div', 'step-footer');
      footer.append(node('span', 'review-tag', '◇ Human review required'), node('span', '', `Risk: ${text(step.risk, 'not assessed')}`));
      item.append(node('h4', 'step-title', text(step.title, 'Review available evidence')), node('p', '', text(step.rationale, 'Review this recommendation before taking any action.')), footer);
      stepList.append(item);
    });
    if (!steps.length) root.append(node('p', 'no-data', 'No next steps supplied. Review the evidence before acting.'));
    root.append(stepList);
    const evidence = values(incident.evidence);
    root.append(detailSection('Supporting evidence', evidence.length));
    const evidenceList = node('ol', 'evidence-list');
    evidence.forEach((entry) => {
      const item = node('li', 'evidence-item');
      const meta = node('div', 'evidence-top');
      meta.append(timestamp(entry.timestamp), node('span', 'evidence-level', text(entry.level, 'info')));
      item.append(meta, node('p', 'evidence-message', text(entry.message)));
      evidenceList.append(item);
    });
    if (evidence.length) root.append(evidenceList);
    else root.append(node('p', 'no-data', 'No log evidence attached.'));
    const runbookIds = values(diagnosis.runbook_ids);
    if (runbookIds.length) {
      const runbooks = node('div', 'runbooks', 'RUNBOOK REFERENCES');
      runbookIds.forEach((id) => runbooks.append(node('span', 'runbook-tag', id)));
      root.append(runbooks);
    }
  }
  function renderActivity(events) {
    $('event-count').textContent = `${events.length} ${events.length === 1 ? 'event' : 'events'}`;
    const fragment = document.createDocumentFragment();
    events.slice().sort((a, b) => (Date.parse(b.timestamp) || 0) - (Date.parse(a.timestamp) || 0)).slice(0, 40).forEach((event) => {
      const item = node('li', 'activity-item');
      const time = timestamp(event.timestamp);
      time.className = 'activity-time';
      const label = node('span', 'activity-event');
      const dot = node('span', 'status-dot');
      dot.setAttribute('aria-hidden', 'true');
      label.append(dot, node('span', '', text(event.event)));
      let detail = event.detail;
      if (detail && typeof detail === 'object') detail = JSON.stringify(detail);
      item.append(time, label, node('span', 'activity-message', text(detail, 'No additional detail.')));
      fragment.append(item);
    });
    if (!events.length) fragment.append(node('li', 'activity-empty', 'No agent events recorded yet.'));
    $('activity-list').replaceChildren(fragment);
  }
  function scheduleRefresh() {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => refresh(), 5000);
  }
  async function refresh(manual = false) {
    if (state.loading || state.busy) { scheduleRefresh(); return; }
    state.loading = true;
    $('refresh-button').disabled = true;
    try {
      renderOverview(await request('/api/overview'));
      if (manual) announce('Console refreshed.');
    } catch (error) {
      state.failures += 1;
      errorBanner(`${error.name === 'AbortError' ? 'The agent did not respond in time.' : error.message} Retrying every 5 seconds.${state.overview ? ' Last received data remains visible and may be stale.' : ' Start the local agent to load telemetry.'}`);
    } finally {
      state.loading = false;
      $('refresh-button').disabled = state.busy;
      scheduleRefresh();
    }
  }
  async function runScenario(scenario, button) {
    if (state.busy || state.loading || !state.overview?.csrf_token) return;
    setBusy(true);
    clearTimeout(state.timer);
    const previousContent = Array.from(button.childNodes).map((child) => child.cloneNode(true));
    button.textContent = 'Generating…';
    announce(`Generating ${scenario} scenario. This may take a moment if model inference is enabled.`);
    try {
      const data = await request('/api/demo', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ops-Token': state.overview.csrf_token }, body: JSON.stringify({ scenario }) });
      state.filter = 'active';
      updateFilters();
      state.selectedId = null;
      renderOverview(data);
      document.querySelectorAll('[data-scenario]').forEach((item) => { item.classList.toggle('selected', item === button); item.setAttribute('aria-pressed', String(item === button)); });
      showToast(`${titleCase(scenario)} scenario generated. Only synthetic telemetry was added.`);
    } catch (error) {
      errorBanner(`${error.name === 'AbortError' ? 'The request timed out. The scenario may still have been generated; refresh to check before retrying.' : error.message} No real service action was requested.`, true);
    } finally {
      button.replaceChildren(...previousContent);
      setBusy(false);
      scheduleRefresh();
    }
  }
  async function acknowledge(id) {
    if (state.busy || state.loading || !state.overview?.csrf_token) return;
    setBusy(true);
    clearTimeout(state.timer);
    const button = $('ack-button');
    if (button) button.textContent = 'Acknowledging…';
    try {
      const result = await request(`/api/incidents/${encodeURIComponent(String(id))}/ack`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ops-Token': state.overview.csrf_token }, body: '{}' });
      if (!result || result.ok !== true) throw new Error('The agent did not confirm acknowledgement. Refresh to check the incident status.');
      renderOverview(await request('/api/overview'));
      showToast('Incident acknowledged locally. No remediation was executed.');
    } catch (error) {
      errorBanner(error.name === 'AbortError' ? 'The request timed out. Refresh to check whether the local acknowledgement was recorded before retrying.' : error.message, true);
      if ($('ack-button')) $('ack-button').textContent = 'Acknowledge incident';
    } finally { setBusy(false); scheduleRefresh(); }
  }
  function updateFilters() {
    ['active', 'all'].forEach((filter) => {
      $(`filter-${filter}`).classList.toggle('active', filter === state.filter);
      $(`filter-${filter}`).setAttribute('aria-pressed', String(filter === state.filter));
    });
  }
  $('refresh-button').addEventListener('click', () => refresh(true));
  $('retry-button').addEventListener('click', () => refresh(true));
  ['active', 'all'].forEach((filter) => { $(`filter-${filter}`).addEventListener('click', () => { state.filter = filter; updateFilters(); renderIncidents(); }); });
  document.querySelectorAll('[data-scenario]').forEach((button) => { button.disabled = true; button.setAttribute('aria-pressed', 'false'); button.addEventListener('click', () => runScenario(button.dataset.scenario, button)); });
  function updateNavigation() {
    const destination = ['#incidents', '#activity'].includes(window.location.hash) ? window.location.hash : '#overview';
    document.querySelectorAll('.nav-item').forEach((link) => {
      const active = link.getAttribute('href') === destination;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }
  window.addEventListener('hashchange', updateNavigation);
  updateNavigation();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('online', () => refresh());
  refresh();
})();
