const $ = (id) => document.getElementById(id);
const elements = (selector) => [...document.querySelectorAll(selector)];
const types = {
  gift: '礼物', gift_invite: '全场邀礼', comment: '弹幕', topic: '投稿', submission: '投稿', manual: '指定',
  like: '点赞', room_join: '进场', follow: '关注', fans_club_join: '粉丝团', unknown: '其他',
};
const gestures = {
  talk: '自然说话', look: '侧目', shrug: '摊手', nod: '点头', point: '指向', lean: '前倾',
  hold: '停顿', wave: '挥手', heart: '比心', hop: '蹦跳',
};
const expressions = {
  neutral: '自然', skeptical: '挑眉', smirk: '偷笑', deadpan: '冷脸',
  soft: '温和', happy: '开心', surprised: '惊讶', grumpy: '嫌弃',
};
const gifts = ['小心心', '玫瑰', '大啤酒', '棒棒糖', '加油鸭', '荧光棒', '礼花筒', '浪漫花火', '跑车'];
const statuses = {
  ignored: '仅记录', queued: '已入队', cooldown: '冷却中', busy: '队列已满', played: '已播',
  stopped: '已急停', merged: '已合并', duplicate: '重复事件', planning: '正在构思', ready: '准备播出',
  selected: '已选回复', skipped: '已跳过', finished: '已播完', ended: '已播完', interrupted: '已中断',
  superseded: '刷屏略过', no_reply: '已略过相似回复', cancelled: '已取消', expired: '已超时', playing: '播出中', error: '播出失败',
};
const voiceStates = { idle: '未启动', loading: '预热中', ready: '已就绪', error: '不可用' };
const emptyLabels = {
  recent: ['等待直播间互动', '收到的弹幕和礼物会出现在这里。'],
  queue: ['待播队列为空', '已安排的回复将按播出顺序排列。'],
  history: ['还没有播出记录', '播出过的台词会保存在这里。'],
};
const listNames = { recent: '互动事件', queue: '待播队列', history: '播出记录' };
const timeFormat = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const dateFormat = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
let snapshot = null;
let online = false;
let pending = false;
let stopping = false;
let selectedList = 'recent';
const archiveKinds = { recent: 'events', history: 'history' };
let archivePages = [];
let archiveIndex = -1;
let archiveRequest = null;
let lastListKey = '';
const desktop = window.doujieDesktop;
let lastModel = '';
const personaField = $('persona-text');
let savedPersona = null, trialKind = 'comment', trialVersion = 0, trialRequest = null, giftTrialNumber = 0;
let feedbackTimer;
let voiceStatus = null;
let uiStream;

function setOptions(select, options) {
  for (const [value, label] of Object.entries(options)) select.add(new Option(label, value));
}
setOptions($('gesture'), gestures);
setOptions($('expression'), expressions);
for (const name of gifts) {
  $('sim-gift').add(new Option(name, name));
  $('trial-gifts').append(new Option(name, name));
}
$('sim-gift').add(new Option('其他礼物…', 'custom'));
$('collector-url').value = location.origin + '/live-events';

function notify(message, error = false) {
  clearTimeout(feedbackTimer);
  $('feedback').textContent = message;
  $('feedback').dataset.error = String(error);
  if (!error) feedbackTimer = setTimeout(() => { $('feedback').textContent = ''; }, 5000);
}

function navigate(target) {
  if (!['live', 'editor', 'persona', 'settings', 'rehearsal'].includes(target)) target = 'live';
  for (const view of elements('.workspace-page')) view.hidden = view.id !== 'view-' + target;
  for (const button of elements('[data-view]')) {
    if (button.dataset.view === target) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (target === 'settings') refreshVoice();
  document.querySelector('.workspace').scrollTop = 0;
  window.scrollTo(0, 0);
}
for (const button of elements('[data-view], [data-go]')) {
  button.addEventListener('click', () => navigate(button.dataset.view || button.dataset.go));
}
for (const button of elements('[data-entry]')) {
  button.addEventListener('click', () => {
    const manual = button.dataset.entry === 'manual';
    for (const other of elements('[data-entry]')) other.setAttribute('aria-pressed', String(other === button));
    $('manual-form').hidden = !manual;
    $('topic-form').hidden = manual;
    $(manual ? 'manual-text' : 'topic').focus();
  });
}
for (const button of elements('[data-list]')) {
  button.addEventListener('click', () => {
    if (selectedList === button.dataset.list) return;
    resetArchive();
    selectedList = button.dataset.list;
    for (const other of elements('[data-list]')) other.setAttribute('aria-pressed', String(other === button));
    renderList();
  });
}

function shortTime(value) {
  if (value == null || value === '') return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return (date.toDateString() === new Date().toDateString() ? '' : dateFormat.format(date) + ' ') + timeFormat.format(date);
}
function tick() { $('clock').textContent = timeFormat.format(new Date()); }
tick();
setInterval(tick, 1000);

function setConnection(connected) {
  online = connected;
  const label = $('connection');
  label.textContent = connected ? '本机在线' : snapshot ? '重连中' : '连接中';
  label.dataset.tone = connected ? 'good' : 'pending';
  renderControls();
}

function renderControls() {
  const unavailable = !online || !snapshot;
  const busy = unavailable || pending || stopping;
  const stopped = Boolean(snapshot?.stopped);
  const auto = (snapshot?.autoEnabled ?? true) && !stopped;
  const stagePresent = Boolean(snapshot?.stageConnected);
  $('launch').firstChild.nodeValue = desktop ? (stagePresent ? '显示舞台 ' : '打开舞台 ') : '预览舞台 ';
  $('launch').title = desktop ? '显示豆姐的竖屏窗口' : '在当前页面预览舞台，可按后退返回导播台';
  $('director-mode').textContent = unavailable ? '等待连接' : stopped ? '已急停' : auto ? '自动模式' : '手动模式';
  $('auto-toggle').disabled = busy || stopped;
  $('auto-toggle').setAttribute('aria-checked', String(auto));
  $('skip').disabled = busy || stopped || !currentTask();
  $('stop').hidden = stopped;
  $('stop').disabled = unavailable || stopping || stopped;
  $('reset').hidden = !stopped;
  $('reset').disabled = busy || !stopped;
  for (const button of elements('[data-play]')) button.disabled = busy || stopped;
  for (const button of elements('[data-online]')) button.disabled = busy;
  for (const button of elements('.event-action')) button.disabled = busy || stopped;
  renderPager();
  renderPersona();
}

function currentTask() {
  return snapshot?.active || snapshot?.queue?.find((task) => task.status === 'planning');
}

function renderProgram() {
  const active = currentTask();
  const stopped = snapshot?.stopped;
  const state = $('program-state');
  const segments = active?.segments || [];
  const index = Number.isInteger(active?.currentSegment) ? active.currentSegment : -1;
  const segment = segments[index];
  state.dataset.state = active ? 'active' : 'idle';
  const preparing = active && index < 0 && segments.length;
  const planning = active?.status === 'planning';
  state.lastElementChild.textContent = stopped ? '已急停' : planning ? '正在构思' : active ? (preparing ? '准备播出' : '正在播出') : snapshot ? '待播' : '同步中';
  $('active-source').textContent = active ? types[active.source] || '现场' : '';
  $('program-title').textContent = stopped ? '播出已暂停' : active ? (active.name ? '回应 ' + active.name : (types[active.source] || '现场') + '播出') : '豆姐待命';
  if (active?.source === 'manual') $('program-title').textContent = '导播送播';
  $('program-prompt').hidden = !active?.prompt;
  $('program-prompt').textContent = active?.prompt || '';
  $('program-line').textContent = stopped ? '解除急停后可继续送播。'
    : planning ? '豆姐正在准备回应…'
    : active ? segment?.text || (preparing ? '等待舞台开始本条表演…' : active.text || '正在演示动作…')
    : snapshot?.autoEnabled ? '正在等下一条弹幕。' : '可以给豆姐投题，或开启自动接话。';
  const tags = [];
  if (active && !planning) {
    if (active.planner === 'fallback') tags.push('本地兜底');
    else if (active.planner === 'deepseek') tags.push('DeepSeek');
    else if (active.planner === 'local') tags.push('内置台词');
    if (index >= 0 && segments.length) tags.push('第 ' + (index + 1) + ' / ' + segments.length + ' 段');
    const gesture = gestures[segment?.gesture || active.cue];
    const expression = expressions[segment?.expression || active.expression];
    if (gesture) tags.push(gesture);
    if (expression) tags.push(expression);
  }
  $('performance-tags').hidden = !tags.length;
  $('performance-tags').replaceChildren(...tags.map((value) => {
    const element = document.createElement('span');
    element.textContent = value;
    return element;
  }));
}

function listRow(item) {
  const recent = selectedList === 'recent';
  const type = item.type || item.source;
  const li = document.createElement('li');
  const tag = document.createElement('span');
  tag.className = 'event-kind'; tag.dataset.kind = type || ''; tag.textContent = types[type] || '现场';
  const body = document.createElement('div');
  body.className = 'event-content';
  const title = document.createElement('p');
  if (recent && type === 'gift') title.textContent = (item.giftName || '礼物') + ' × ' + (item.displayCount || 1);
  else title.textContent = item.content || (selectedList === 'history' ? item.text : item.prompt || item.text) || item.giftName || item.countText || gestures[item.cue] || types[type] || '互动';
  const sub = document.createElement('small');
  sub.textContent = [item.nickname || item.name, statuses[item.status], shortTime(item.capturedAt || item.finishedAt || item.startedAt || item.at)].filter(Boolean).join(' · ');
  body.append(title, sub);
  li.append(tag, body);
  if (recent && item.type === 'comment' && item.status !== 'played' && item.content && item.eventId) {
    const send = document.createElement('button');
    send.type = 'button'; send.className = 'event-action'; send.textContent = '回复';
    send.dataset.eventId = item.eventId;
    if (item.roomId) send.dataset.roomId = item.roomId;
    send.setAttribute('aria-label', '回复 ' + (item.nickname || '观众') + ' 的弹幕');
    send.disabled = !online || pending || stopping || snapshot?.stopped;
    li.append(send);
  }
  return li;
}

function archiveCursor() {
  if (archiveIndex >= 0) return archivePages[archiveIndex].nextCursor;
  return snapshot?.archiveBefore?.[archiveKinds[selectedList]];
}

function renderPager() {
  const past = archiveIndex >= 0;
  const hasOlder = archiveIndex + 1 < archivePages.length || Number.isSafeInteger(archiveCursor());
  $('archive-nav').hidden = !past && !hasOlder;
  $('archive-newest').hidden = !past;
  $('archive-newer').hidden = archiveIndex < 1;
  $('archive-older').hidden = !hasOlder;
  $('archive-older').disabled = !online || Boolean(archiveRequest);
  $('archive-older').textContent = archiveRequest ? '加载中…' : '更早记录';
}

function resetArchive() {
  archiveRequest?.abort();
  archiveRequest = null;
  archivePages = [];
  archiveIndex = -1;
  $('event-list').scrollTop = 0;
}

$('archive-newest').addEventListener('click', () => { resetArchive(); renderList(); });
$('archive-newer').addEventListener('click', () => {
  archiveRequest?.abort();
  archiveRequest = null;
  archiveIndex--;
  $('event-list').scrollTop = 0;
  renderList();
});
$('archive-older').addEventListener('click', async () => {
  if (archiveRequest || !online) return;
  if (archiveIndex + 1 === archivePages.length) {
    const kind = archiveKinds[selectedList];
    const before = archiveCursor();
    if (!kind || !Number.isSafeInteger(before)) return;
    const request = new AbortController();
    archiveRequest = request;
    renderPager();
    try {
      const params = new URLSearchParams({kind, before: String(before), limit: '60'});
      const response = await fetch('/api/archive?' + params, {cache: 'no-store', signal: AbortSignal.any([request.signal, AbortSignal.timeout(10000)])});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const page = await response.json();
      if (!Array.isArray(page.items)) throw new Error('记录格式错误');
      if (request !== archiveRequest) return;
      archivePages.push(page);
    } catch (error) {
      if (!request.signal.aborted) notify('读取历史记录失败，' + error.message, true);
      return;
    } finally {
      if (archiveRequest === request) archiveRequest = null;
      renderPager();
    }
  }
  archiveIndex++;
  $('event-list').scrollTop = 0;
  renderList();
});

function renderList() {
  const rows = archiveIndex < 0 ? snapshot?.[selectedList] || [] : archivePages[archiveIndex].items;
  renderPager();
  const key = selectedList + JSON.stringify(rows);
  if (key === lastListKey) return;
  lastListKey = key;
  const list = $('event-list');
  const empty = $('event-empty');
  empty.hidden = rows.length > 0;
  empty.querySelector('strong').textContent = archiveIndex >= 0 ? '没有更早的记录' : emptyLabels[selectedList][0];
  empty.querySelector('p').textContent = archiveIndex >= 0 ? '' : emptyLabels[selectedList][1];
  list.setAttribute('aria-label', listNames[selectedList]);
  list.replaceChildren(...rows.map(listRow));
}

function renderServices() {
  const llm = snapshot?.llm;
  const voice = voiceStatus || snapshot?.voice;
  $('llm-state').textContent = !llm ? '同步中' : llm.configured ? '已配置' : '本地接话';
  $('llm-state').dataset.tone = llm?.configured ? 'good' : 'pending';
  if (llm?.model && llm.model !== lastModel) {
    if ($('model-name').value === lastModel) $('model-name').value = llm.model;
    lastModel = llm.model;
  }
  $('model-name').placeholder = llm?.model || 'deepseek-flash';
  $('api-key').placeholder = llm?.configured ? '已配置，留空可保留当前密钥' : '输入 DeepSeek API Key';
  $('model-note').textContent = [llm?.message, llm?.keyNotice || 'Windows 会使用当前账户加密保存手动输入的密钥。'].filter(Boolean).join(' · ');
  $('forget-key').hidden = !llm?.keySaved;
  $('voice-state').textContent = voiceStates[voice?.state] || '等待状态';
  $('voice-note').textContent = voice?.message || '';
  const rate = voice?.rate;
  if (Number.isFinite(rate) && !pending) {
    const select = $('speech-rate');
    if (![...select.options].some(option => option.value === String(rate))) {
      select.add(new Option(rate + '×', String(rate)));
    }
    select.value = String(rate);
  }
  $('stage-state').textContent = !snapshot ? '等待状态' : snapshot.stageConnected ? '已连接' : '未连接';
}

function clearTrial() {
  trialVersion++;
  $('trial-result').hidden = true;
  $('trial-lines').replaceChildren();
}

function renderPersona() {
  const llm = snapshot?.llm;
  const loaded = typeof llm?.persona === 'string' && typeof llm?.defaultPersona === 'string';
  if (loaded && savedPersona !== llm.persona) {
    if (savedPersona === null || personaField.value.trim() === savedPersona) {
      if (personaField.value !== llm.persona) clearTrial();
      personaField.value = llm.persona;
      personaField.scrollTop = 0;
    }
    savedPersona = llm.persona;
  }
  if (loaded) personaField.maxLength = llm.personaMaxLength || 1200;
  const draft = personaField.value.trim();
  const dirty = loaded && draft !== savedPersona;
  personaField.disabled = !loaded;
  const state = $('persona-state');
  state.textContent = !loaded ? '同步中' : dirty ? '草稿未保存' : draft === llm.defaultPersona ? '默认人设' : '自定义 · 已保存';
  state.dataset.tone = dirty || !loaded ? 'pending' : 'good';
  $('persona-default').disabled = !loaded || personaField.value === llm.defaultPersona;
  $('persona-save').disabled = !online || pending || stopping || !dirty || !draft;
  $('trial-start').disabled = !online || !loaded || !draft || Boolean(trialRequest);
  $('trial-start').textContent = trialRequest ? '正在生成…' : dirty ? '按草稿试词' : '生成试词';
  $('trial-note').textContent = !loaded ? '' : !llm.configured
    ? '当前使用内置毒舌台词。配置 DeepSeek 后可试自定义人设。'
    : trialKind === 'gift' ? '首句即时接礼物，收尾交给 DeepSeek 按当前人设改写。'
    : '笑声和表情直接用内置短句。想试听人设，可以发一个具体问题。';
}

personaField.addEventListener('input', () => { clearTrial(); renderPersona(); });
$('persona-default').addEventListener('click', () => {
  personaField.value = snapshot.llm.defaultPersona;
  clearTrial();
  renderPersona();
  personaField.focus();
  personaField.setSelectionRange(0, 0);
  personaField.scrollTop = 0;
});
$('persona-form').addEventListener('submit', async event => {
  event.preventDefault();
  const persona = personaField.value.trim();
  if (!persona || persona === savedPersona) return;
  await control({action: 'settings', persona}, '人设已保存，下次 DeepSeek 写词时生效。');
});

for (const button of elements('[data-trial-kind]')) {
  button.addEventListener('click', () => {
    if (trialKind === button.dataset.trialKind) return;
    trialKind = button.dataset.trialKind;
    const gift = trialKind === 'gift';
    for (const tab of elements('[data-trial-kind]')) tab.setAttribute('aria-pressed', String(tab === button));
    $('trial-comment-field').hidden = $('trial-comment').disabled = gift;
    $('trial-gift-fields').hidden = $('trial-gift').disabled = $('trial-count').disabled = !gift;
    clearTrial();
    renderPersona();
  });
}
$('persona-trial').addEventListener('input', clearTrial);
$('persona-trial').addEventListener('submit', async event => {
  event.preventDefault();
  if (!online || trialRequest) return;
  const payload = {source: trialKind, persona: personaField.value.trim()};
  if (!payload.persona) { personaField.focus(); return; }
  if (trialKind === 'gift') {
    payload.giftName = $('trial-gift').value.trim();
    payload.giftCount = $('trial-count').valueAsNumber;
    if (!payload.giftName) { $('trial-gift').focus(); return; }
    payload.variant = giftTrialNumber++;
  } else {
    payload.text = $('trial-comment').value.trim();
    if (!payload.text) { $('trial-comment').focus(); return; }
  }
  clearTrial();
  const version = trialVersion;
  trialRequest = new AbortController();
  renderPersona();
  try {
    const response = await fetch('/api/persona/preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
      signal: AbortSignal.any([trialRequest.signal, AbortSignal.timeout(15000)]),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'HTTP ' + response.status);
    const lines = result.segments?.map(part => part.text).filter(Boolean);
    if (!lines?.length) throw new Error('没有收到试词');
    if (version !== trialVersion) return;
    const source = result.mode === 'deepseek' ? (trialKind === 'gift' ? '内置开场 · DeepSeek 收尾' : 'DeepSeek 试词')
      : result.mode === 'fallback' ? '本次回退到内置台词' : '内置台词';
    $('trial-source').textContent = source;
    $('trial-lines').replaceChildren(...lines.map(text => {
      const line = document.createElement('p');
      line.textContent = text;
      return line;
    }));
    $('trial-result').hidden = false;
    if (!$('view-persona').hidden) $('trial-result').scrollIntoView({block:'nearest'});
  } catch (error) {
    if (version === trialVersion && !trialRequest.signal.aborted) notify('试词失败，' + error.message, true);
  } finally {
    trialRequest = null;
    renderPersona();
  }
});

function accept(next, allowRestart = false) {
  if (!next || !Number.isSafeInteger(next.revision)) return;
  if (!allowRestart && snapshot && next.revision < snapshot.revision) return;
  snapshot = next;
  if (next.voice) voiceStatus = next.voice;
  setConnection(true);
  $('queue-count').textContent = $('sim-depth').textContent = String(next.queueDepth || 0);
  $('sim-auto').textContent = next.stopped ? '已急停' : next.autoEnabled ? '已开启' : '已关闭';
  const latest = next.recent?.[0];
  $('sim-latest').textContent = latest ? [types[latest.type], latest.nickname, shortTime(latest.capturedAt)].filter(Boolean).join(' · ') : '暂无';
  renderProgram();
  renderList();
  renderServices();
}

async function refreshState() {
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (response.ok) accept(await response.json(), !online);
  } catch {
    if (!uiStream || uiStream.readyState !== EventSource.OPEN) setConnection(false);
  }
}
async function refreshVoice() {
  try {
    const response = await fetch('/api/voice/status', { cache: 'no-store' });
    if (response.ok) {
      voiceStatus = await response.json();
      renderServices();
    }
  } catch { /* The control stream handles connection feedback. */ }
}
if ('EventSource' in window) {
  uiStream = new EventSource('/api/stream');
  let first = true;
  uiStream.onopen = () => { first = true; };
  uiStream.addEventListener('state', (event) => {
    try {
      accept(JSON.parse(event.data), first);
      first = false;
    } catch { /* An invalid update is superseded by the next state. */ }
  });
  uiStream.onerror = () => setConnection(false);
} else {
  setInterval(refreshState, 2500);
}
refreshState();
setInterval(() => { if (!$('view-settings').hidden && !document.hidden) refreshVoice(); }, 4000);
window.addEventListener('pagehide', () => { uiStream?.close(); trialRequest?.abort(); }, { once: true });

async function post(path, payload, message) {
  const emergency = payload.action === 'stop';
  if (!online || !snapshot || stopping || (!emergency && pending)) return false;
  if (emergency) stopping = true; else pending = true;
  renderControls();
  try {
    const response = await fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(10000),
    });
    const update = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new Error(update?.error || 'HTTP ' + response.status);
    if (update?.revision !== undefined) accept(update);
    notify(typeof message === 'function' ? message(update) : message);
    return true;
  } catch (err) {
    notify('操作未完成：' + err.message, true);
    return false;
  } finally {
    if (emergency) stopping = false; else pending = false;
    renderControls();
  }
}
const control = (payload, message) => post('/api/control', payload, message);

$('speech-rate').addEventListener('change', async event => {
  const rate = Number(event.target.value);
  await control({action:'speech_rate', rate}, '新合成的台词将使用 ' + rate + '× 语速。');
  renderServices();
});

$('launch').addEventListener('click', async () => {
  if (!desktop) {
    window.location.assign('/stage.html');
    return;
  }
  try {
    if (!await desktop.openStage()) notify('舞台窗口暂时无法显示。', true);
  } catch {
    notify('舞台窗口暂时无法显示。', true);
  }
});
$('auto-toggle').addEventListener('click', () => {
  const enabled = !snapshot.autoEnabled;
  control({ action: 'auto', enabled }, enabled ? '已开启自动接话。' : '已关闭自动接话。');
});
$('stop').addEventListener('click', () => control({ action: 'stop' }, '已急停并清空待播队列。'));
$('reset').addEventListener('click', () => control({ action: 'reset' }, '已解除急停，可手动送播或重新开启自动接话。'));
$('skip').addEventListener('click', () => control({ action: 'skip', id: currentTask()?.id }, '已跳过本条。'));
$('event-list').addEventListener('click', (event) => {
  const button = event.target.closest('.event-action');
  if (button) control({ action: 'reply', eventId: button.dataset.eventId, roomId: button.dataset.roomId }, '已安排豆姐回复这条弹幕。');
});
$('topic-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = $('topic').value.trim();
  const name = $('topic-name').value.trim();
  if (!text) { $('topic').focus(); notify('请先写下投稿内容。', true); return; }
  if (await control({ action: 'submit', text, name }, '投稿已送入待播队列。')) {
    if ($('topic').value.trim() === text) $('topic').value = '';
    if ($('topic-name').value.trim() === name) $('topic-name').value = '';
  }
});
$('manual-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = $('manual-text').value.trim();
  const cue = $('gesture').value;
  if (!text && cue === 'talk') { $('manual-text').focus(); notify('请输入台词，或选择要演示的动作。', true); return; }
  const ok = await control({ action: 'manual', cue, expression: $('expression').value, text }, '指定表演已送入队列。');
  if (ok && $('manual-text').value.trim() === text) $('manual-text').value = '';
});
$('model-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const model = $('model-name').value.trim();
  const key = $('api-key').value.trim();
  if (!model && !key) { notify('请输入模型名或密钥。', true); return; }
  const payload = { action: 'settings' };
  if (model) payload.model = model;
  if (key) payload.apiKey = key;
  const feedback = update => key && update?.llm?.keyNotice ? update.llm.keyNotice : '模型设置已保存。';
  if (await control(payload, feedback) && $('api-key').value.trim() === key) $('api-key').value = '';
});
$('forget-key').addEventListener('click', async () => {
  if (await control({action: 'settings', apiKey: ''}, '已移除本机保存的密钥。')) $('api-key').value = '';
});

function updateSimFields() {
  const gift = $('sim-type').value === 'gift';
  const comment = $('sim-type').value === 'comment';
  const custom = gift && $('sim-gift').value === 'custom';
  $('sim-comment-fields').hidden = !comment;
  $('sim-gift-fields').hidden = !gift;
  $('sim-combo').hidden = !gift;
  $('custom-gift-field').hidden = !custom;
  $('sim-comment').disabled = !comment;
  $('sim-count').disabled = !gift;
  $('sim-custom').disabled = !custom;
  $('sim-custom').required = custom;
}
$('sim-type').addEventListener('change', updateSimFields);
$('sim-gift').addEventListener('change', updateSimFields);
updateSimFields();

function simulate(combo) {
  const form = $('sim-form');
  if (!form.reportValidity()) return;
  const type = $('sim-type').value;
  const nickname = $('sim-name').value.trim();
  if (!nickname) { $('sim-name').focus(); notify('请输入观众昵称。', true); return; }
  const content = $('sim-comment').value.trim();
  const giftName = $('sim-gift').value === 'custom' ? $('sim-custom').value.trim() : $('sim-gift').value;
  if (type === 'comment' && !content) { $('sim-comment').focus(); notify('请输入弹幕内容。', true); return; }
  if (type === 'gift' && !giftName) { $('sim-custom').focus(); notify('请输入礼物名称。', true); return; }
  const counts = combo ? [1, 2, 3] : [Number($('sim-count').value) || 1];
  const captured = Date.now();
  const comboId = type === 'gift' ? crypto.randomUUID() : undefined;
  const events = counts.map((count, index) => ({
    eventId: crypto.randomUUID(), roomId: '10000', type,
    capturedAt: new Date(captured + index).toISOString(),
    actor: { nickname, userId: 'rehearsal-' + nickname },
    data: type === 'gift' ? { giftName, displayCount: count, comboId } : type === 'comment' ? { content } : {},
    rawText: type === 'comment' ? content : giftName && type === 'gift' ? nickname + ' 送出 ' + giftName + ' × ' + count : nickname + ' ' + types[type],
  }));
  const suffix = snapshot?.autoEnabled && !snapshot?.stopped ? '已送入直播事件入口。' : '已记录，自动接话当前关闭。';
  post('/live-events', { schemaVersion: 1, events }, (combo ? '三连击' : '模拟' + types[type]) + suffix);
}
$('sim-form').addEventListener('submit', (event) => { event.preventDefault(); simulate(false); });
$('sim-combo').addEventListener('click', () => simulate(true));
$('room-inventory').addEventListener('toggle', async () => {
  const list = $('room-inventory-items');
  if (!$('room-inventory').open || list.dataset.loading || list.querySelector('dt')) return;
  list.dataset.loading = 'true';
  try {
    const response = await fetch('./assets/studio-inventory.json');
    if (!response.ok) throw new Error();
    const {items} = await response.json();
    const rows = document.createDocumentFragment();
    for (const item of items) {
      const title = document.createElement('dt'), detail = document.createElement('dd');
      title.textContent = item.name;
      detail.textContent = item.location + '。' + item.appearance + '。';
      rows.append(title, detail);
    }
    list.replaceChildren(rows);
  } catch {
    list.textContent = '舞台清单加载失败，收起后可重试。';
  } finally {
    delete list.dataset.loading;
  }
});
