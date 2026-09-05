const ui = {
  runtime: document.querySelector('#runtime'),
  profileList: document.querySelector('#profileList'),
  coachList: document.querySelector('#coachList'),
  asOf: document.querySelector('#asOf'),
  agentTitle: document.querySelector('#agentTitle'),
  agentHint: document.querySelector('#agentHint'),
  startButton: document.querySelector('#startButton'),
  endButton: document.querySelector('#endButton'),
  chatLog: document.querySelector('#chatLog'),
  quickPrompts: document.querySelector('#quickPrompts'),
  chatForm: document.querySelector('#chatForm'),
  messageInput: document.querySelector('#messageInput'),
  sendButton: document.querySelector('#sendButton'),
  stateSummary: document.querySelector('#stateSummary'),
  roomStatus: document.querySelector('#roomStatus'),
  roomDetail: document.querySelector('#roomDetail'),
  riskStatus: document.querySelector('#riskStatus'),
  riskDetail: document.querySelector('#riskDetail'),
  cycleDate: document.querySelector('#cycleDate'),
  envelopeList: document.querySelector('#envelopeList'),
  toast: document.querySelector('#toast'),
};

const state = {
  profiles: [],
  coaches: [],
  profileId: null,
  coachPersona: '온순냥',
  profile: null,
  sessionId: null,
  active: false,
  sending: false,
  starting: false,
  loading: false,
  viewVersion: 0,
  messageController: null,
};

const numeric = value => {
  if (value === null || value === undefined || typeof value === 'boolean' || typeof value === 'object') return NaN;
  if (typeof value === 'string' && !value.trim()) return NaN;
  return Number(value);
};

const money = value => {
  const number = numeric(value);
  return Number.isFinite(number) ? `${Math.round(number).toLocaleString('ko-KR')}원` : '자료 없음';
};

const percent = value => {
  const number = numeric(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : '자료 없음';
};

const dateLabel = value => value ? String(value).replaceAll('-', '.') : '없음';

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'content-type': 'application/json', ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `요청 실패 (${response.status})`);
  return payload;
}

function toast(message) {
  ui.toast.textContent = message;
  ui.toast.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ui.toast.classList.remove('show'), 2600);
}

function setActive(active) {
  state.active = active;
  ui.startButton.disabled = active || state.starting || state.loading || !state.profileId || !state.coachPersona;
  ui.endButton.disabled = !active && !state.starting;
  ui.messageInput.disabled = !active;
  ui.sendButton.disabled = !active || state.sending;
  ui.messageInput.placeholder = active ? '평소처럼 질문하거나 금융 작업을 부탁하세요' : '대화를 시작한 뒤 메시지를 입력하세요';
}

function renderProfiles() {
  ui.profileList.replaceChildren();
  state.profiles.forEach(profile => {
    const button = document.createElement('button');
    button.className = `choice${profile.id === state.profileId ? ' selected' : ''}`;
    button.type = 'button';
    const name = document.createElement('strong');
    name.textContent = `${profile.id} · ${profile.name}`;
    const description = document.createElement('small');
    description.textContent = profile.description || '더미 금융 사용자';
    button.append(name, description);
    button.addEventListener('click', () => selectProfile(profile.id));
    ui.profileList.appendChild(button);
  });
}

function renderCoaches() {
  ui.coachList.replaceChildren();
  state.coaches.forEach(coach => {
    const button = document.createElement('button');
    button.className = `coach-option${coach.id === state.coachPersona ? ' selected' : ''}`;
    button.type = 'button';
    const name = document.createElement('strong');
    name.textContent = coach.name || coach.id;
    const description = document.createElement('small');
    description.textContent = coach.description || '';
    button.append(name, description);
    button.addEventListener('click', async () => {
      state.coachPersona = coach.id;
      renderCoaches();
      renderAgentHeader();
      await endConversation(true);
      setActive(false);
    });
    ui.coachList.appendChild(button);
  });
}

function stat(label, value) {
  const card = document.createElement('div');
  card.className = 'stat';
  const small = document.createElement('small');
  small.textContent = label;
  const strong = document.createElement('strong');
  strong.textContent = value;
  card.append(small, strong);
  return card;
}

function renderState(payload) {
  state.profile = payload;
  const profile = payload.profile || {};
  const data = payload.state || {};
  const risk = payload.risk || {};
  const room = payload.room || {};
  renderAgentHeader();
  ui.asOf.value = data.as_of || profile.as_of || '';
  ui.stateSummary.className = 'state-summary';
  ui.stateSummary.replaceChildren();

  const banner = document.createElement('div');
  banner.className = 'profile-banner';
  const asOf = document.createElement('small');
  asOf.textContent = `${dateLabel(data.as_of)} 기준 · ${profile.source || 'DEMO'}`;
  const name = document.createElement('strong');
  name.textContent = profile.name || profile.id || '금융 사용자';
  const description = document.createElement('p');
  description.textContent = profile.description || '';
  banner.append(asOf, name, description);
  ui.stateSummary.append(
    banner,
    stat('현재 유동성', money(data.liquidity)),
    stat('비상금', money(data.emergency_fund)),
    stat('다음 수입', dateLabel(data.next_income_date)),
    stat('예상 수입', money(data.expected_income)),
    stat('약정 지출', `${Array.isArray(data.committed) ? data.committed.length : 0}건`),
    stat('가속도', Number.isFinite(numeric(data.acceleration)) ? `${numeric(data.acceleration).toFixed(2)}배` : '자료 없음'),
  );

  ui.roomStatus.textContent = room.level ? `${room.level} · ${room.weather || ''}` : '-';
  ui.roomDetail.textContent = room.avatar_mood && room.avatar_action
    ? `표정 ${room.avatar_mood} · 행동 ${room.avatar_action}`
    : '날씨 · 표정 · 행동';
  ui.riskStatus.textContent = risk.level ? `${risk.level} · ${risk.risk_score ?? '-'}점` : '-';
  ui.riskDetail.textContent = risk.level
    ? `전체 부족 ${percent(risk.shortfall_prob)} · 카드 부족 ${percent(risk.card_shortfall_prob)} · 예상 부족 ${money(risk.expected_shortfall)}`
    : '위험 점수와 확률은 FDT 엔진이 계산합니다.';
  ui.cycleDate.textContent = dateLabel(data.as_of);
  renderEnvelopes(data.envelopes || [], room.board_progress || {});
  renderProfiles();
  setActive(false);
}

function renderAgentHeader() {
  const profile = state.profile?.profile || {};
  const data = state.profile?.state || {};
  ui.agentTitle.textContent = `${state.coachPersona} · ${profile.name || profile.id || 'FDT 코치'}`;
  ui.agentHint.textContent = `${dateLabel(data.as_of)} 기준 · ${state.profile?.source || 'DEMO'} 금융 상태`;
}

function renderEnvelopes(envelopes, progress) {
  ui.envelopeList.replaceChildren();
  envelopes.forEach(item => {
    const row = document.createElement('div');
    row.className = 'envelope-row';
    const meta = document.createElement('div');
    meta.className = 'envelope-meta';
    const label = document.createElement('strong');
    label.textContent = item.envelope || '기타';
    const amount = document.createElement('span');
    amount.textContent = `${money(item.spent)} / ${money(item.budget)}`;
    meta.append(label, amount);
    const track = document.createElement('div');
    track.className = 'progress';
    const fill = document.createElement('i');
    const ratio = Number(progress[item.envelope]);
    fill.style.width = `${Number.isFinite(ratio) ? Math.max(0, Math.min(1.2, ratio)) * 100 : 0}%`;
    track.appendChild(fill);
    row.append(meta, track);
    ui.envelopeList.appendChild(row);
  });
}

function appendMessage(role, message, route = [], results = []) {
  if (ui.chatLog.querySelector('.empty')) ui.chatLog.replaceChildren();
  const row = document.createElement('div');
  row.className = `message ${role}`;
  const wrap = document.createElement('div');
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = message;
  wrap.appendChild(bubble);
  if (results.length) results.forEach(result => {
    const visualization = renderVisualization(result.visualization, result.data, result.tool);
    if (visualization) wrap.appendChild(visualization);
  });
  if (route.length) {
    const trace = document.createElement('div');
    trace.className = 'route';
    route.forEach(step => {
      const chip = document.createElement('span');
      chip.textContent = step;
      trace.appendChild(chip);
    });
    wrap.appendChild(trace);
  }
  row.appendChild(wrap);
  ui.chatLog.appendChild(row);
  ui.chatLog.scrollTop = ui.chatLog.scrollHeight;
}

function formatValue(value, format) {
  if (value === null || value === undefined || value === '') return '자료 없음';
  if (format === 'money') return money(value);
  if (format === 'date') return dateLabel(value);
  if (format === 'percent') return percent(value);
  return String(value);
}

function forecastChart(series) {
  const points = series.filter(item => [item.low, item.value, item.high].every(value => Number.isFinite(numeric(value))));
  if (!points.length) return null;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 520 180');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', '예측 잔액 중앙값과 P10에서 P90까지의 범위');
  svg.style.width = '100%';
  const low = Math.min(0, ...points.map(item => numeric(item.low)));
  const high = Math.max(1, ...points.map(item => numeric(item.high)));
  const x = index => 16 + index / Math.max(1, points.length - 1) * 488;
  const y = value => 160 - (numeric(value) - low) / Math.max(1, high - low) * 140;
  const band = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  const upper = points.map((item, index) => `${x(index)},${y(item.high)}`);
  const lower = points.map((item, index) => `${x(index)},${y(item.low)}`).reverse();
  band.setAttribute('points', [...upper, ...lower].join(' '));
  band.setAttribute('fill', 'currentColor');
  band.setAttribute('opacity', '0.15');
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  line.setAttribute('points', points.map((item, index) => `${x(index)},${y(item.value)}`).join(' '));
  line.setAttribute('fill', 'none');
  line.setAttribute('stroke', 'currentColor');
  line.setAttribute('stroke-width', '2');
  svg.append(band, line);
  return svg;
}

function renderVisualization(spec, data, tool) {
  if (!spec || typeof spec !== 'object') return null;
  const box = document.createElement('section');
  box.className = 'result';
  const title = document.createElement('h4');
  title.textContent = spec.title || tool || '엔진 결과';
  box.appendChild(title);
  if (spec.status) {
    const status = document.createElement('p');
    status.textContent = `상태: ${spec.status}`;
    box.appendChild(status);
  }
  if (spec.type === 'table') {
    const table = document.createElement('table');
    table.className = 'viz-table';
    const head = document.createElement('tr');
    (spec.columns || []).forEach(column => {
      const cell = document.createElement('th');
      cell.textContent = column.label || column.key;
      head.appendChild(cell);
    });
    table.appendChild(head);
    (spec.rows || []).forEach(item => {
      const row = document.createElement('tr');
      (spec.columns || []).forEach(column => {
        const cell = document.createElement('td');
        cell.textContent = formatValue(item[column.key], column.format);
        row.appendChild(cell);
      });
      table.appendChild(row);
    });
    box.appendChild(table);
    return box;
  }
  if (spec.type === 'forecast_line') {
    const chart = forecastChart(spec.series || []);
    if (chart) box.appendChild(chart);
    const table = document.createElement('table');
    table.className = 'viz-table';
    const head = document.createElement('tr');
    ['날짜', 'P10', 'P50', 'P90'].forEach(label => { const cell = document.createElement('th'); cell.textContent = label; head.appendChild(cell); });
    table.appendChild(head);
    (spec.series || []).forEach(item => {
      const row = document.createElement('tr');
      [item.label, money(item.low), money(item.value), money(item.high)].forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.appendChild(cell); });
      table.appendChild(row);
    });
    box.appendChild(table);
    return box;
  }
  const series = (spec.series || []).filter(item => Number.isFinite(numeric(item.value)));
  const max = Math.max(1, ...series.map(item => Math.abs(Number(item.value)) || 0));
  series.forEach(item => {
    const row = document.createElement('div');
    row.className = 'result-row';
    const label = document.createElement('span');
    label.textContent = item.label || '항목';
    const track = document.createElement('div');
    track.className = 'bar';
    const fill = document.createElement('i');
    fill.style.width = `${Math.max(2, Math.abs(Number(item.value) || 0) / max * 100)}%`;
    track.appendChild(fill);
    const value = document.createElement('strong');
    value.textContent = spec.unit === 'KRW' ? money(item.value) : String(item.value);
    row.append(label, track, value);
    box.appendChild(row);
  });
  return box;
}

async function selectProfile(profileId, requestedAsOf = '') {
  const ending = endConversation(true);
  const version = state.viewVersion;
  state.loading = true;
  setActive(false);
  try {
    await ending;
    if (version !== state.viewVersion) return;
    const suffix = requestedAsOf ? `?as_of=${encodeURIComponent(requestedAsOf)}` : '';
    const payload = await api(`/api/profiles/${encodeURIComponent(profileId)}${suffix}`);
    if (version !== state.viewVersion) return;
    state.profileId = profileId;
    renderState(payload);
    ui.chatLog.replaceChildren(Object.assign(document.createElement('div'), { className: 'empty', textContent: '대화를 시작하면 엔진 결과를 이곳에 표시합니다.' }));
    toast(`${payload.profile?.name || profileId} 금융 프로필을 불러왔습니다.`);
  } catch (error) {
    if (version === state.viewVersion) toast(error.message);
  } finally {
    if (version === state.viewVersion) {
      state.loading = false;
      setActive(state.active);
    }
  }
}

async function startConversation() {
  if (!state.profileId || state.active || state.starting || state.loading) return;
  const version = state.viewVersion;
  state.starting = true;
  setActive(false);
  try {
    const body = { profile_id: state.profileId, coach_persona: state.coachPersona };
    if (ui.asOf.value) body.as_of = ui.asOf.value;
    const payload = await api('/api/chat/start', { method: 'POST', body: JSON.stringify(body) });
    if (version !== state.viewVersion) {
      // A cancelled start may still have created a server-side session.
      await api('/api/chat/end', { method: 'POST', body: JSON.stringify({ session_id: payload.session_id }) }).catch(() => {});
      return;
    }
    state.sessionId = payload.session_id;
    appendMessage('assistant', payload.message, payload.route || []);
    setActive(true);
    ui.messageInput.focus();
  } catch (error) {
    if (version === state.viewVersion) toast(error.message);
  } finally {
    if (version === state.viewVersion) {
      state.starting = false;
      setActive(state.active);
    }
  }
}

async function endConversation(silent = false) {
  const sessionId = state.sessionId;
  const version = ++state.viewVersion;
  state.messageController?.abort();
  state.messageController = null;
  state.sessionId = null;
  state.sending = false;
  state.starting = false;
  state.loading = false;
  setActive(false);
  if (!sessionId) return;
  try {
    const payload = await api('/api/chat/end', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) });
    if (!silent && version === state.viewVersion) appendMessage('assistant', payload.message, payload.route || []);
  } catch (error) {
    if (!silent && version === state.viewVersion) toast(error.message);
  }
}

async function sendMessage(message) {
  const clean = message.trim();
  if (!clean || !state.active || state.sending) return;
  const sessionId = state.sessionId;
  const version = state.viewVersion;
  const controller = new AbortController();
  const current = () => version === state.viewVersion && sessionId === state.sessionId && state.active;
  state.messageController = controller;
  state.sending = true;
  setActive(true);
  appendMessage('user', clean);
  try {
    const payload = await api('/api/chat/message', {
      method: 'POST', signal: controller.signal,
      body: JSON.stringify({ session_id: sessionId, message: clean }),
    });
    if (current()) appendMessage('assistant', payload.message, payload.route || [], payload.results || []);
  } catch (error) {
    if (current() && error.name !== 'AbortError') appendMessage('assistant', `요청을 처리하지 못했어요. ${error.message}`);
  } finally {
    if (current()) {
      state.sending = false;
      state.messageController = null;
      setActive(true);
      ui.messageInput.focus();
    }
  }
}

ui.startButton.addEventListener('click', startConversation);
ui.endButton.addEventListener('click', () => endConversation(false));
ui.chatForm.addEventListener('submit', event => {
  event.preventDefault();
  const message = ui.messageInput.value;
  ui.messageInput.value = '';
  ui.messageInput.style.height = '';
  sendMessage(message);
});
ui.messageInput.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); ui.chatForm.requestSubmit(); }
});
ui.messageInput.addEventListener('input', () => {
  ui.messageInput.style.height = 'auto';
  ui.messageInput.style.height = `${Math.min(130, ui.messageInput.scrollHeight)}px`;
});
ui.quickPrompts.addEventListener('click', event => {
  const button = event.target.closest('button[data-prompt]');
  if (button) {
    if (!state.active) toast('먼저 대화를 시작하세요.');
    else sendMessage(button.dataset.prompt);
  }
});
ui.asOf.addEventListener('change', () => { if (state.profileId) selectProfile(state.profileId, ui.asOf.value); });

async function boot() {
  setActive(false);
  try {
    const [health, profiles] = await Promise.all([api('/api/health'), api('/api/profiles')]);
    ui.runtime.classList.add('online');
    ui.runtime.replaceChildren();
    const dot = document.createElement('span');
    const source = health.source || 'DEMO';
    const engine = health.engine_ready ? 'ready' : 'not ready';
    const llm = health.llm_ready ? `ready (${health.llm_model || 'configured'})` : 'not ready';
    const fallback = health.fallback ? 'ON (template)' : 'OFF';
    ui.runtime.append(
      dot,
      document.createTextNode(` source: ${source} · engine_ready: ${engine} · LLM: ${llm} · fallback: ${fallback}`),
    );
    state.profiles = profiles.profiles || [];
    state.coaches = profiles.coach_personas || [
      { id: '도도냥', name: '도도냥', description: '짧고 직설적인 코치' },
      { id: '온순냥', name: '온순냥', description: '부드럽고 격려하는 코치' },
      { id: '지방냥', name: '지방냥', description: '구수한 사투리 코치' },
    ];
    renderCoaches();
    if (state.profiles.length) await selectProfile(state.profiles[0].id);
  } catch (error) {
    ui.runtime.classList.add('offline');
    ui.runtime.textContent = '로컬 서버 연결 실패';
    toast(error.message);
  }
}

boot();
