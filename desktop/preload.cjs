// Trusted project controls in an isolated preload; no raw IPC or path setter is exposed.
const { ipcRenderer } = require('electron');

// These display helpers keep missing measurements distinct from measured zero.
function resourceNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}
function resourcePercent(used, total, measured) {
  const value = resourceNumber(measured);
  if (value !== null) return Math.min(value, 100);
  used = resourceNumber(used); total = resourceNumber(total);
  return used !== null && total !== null && total > 0 ? Math.min(100, used / total * 100) : null;
}
function resourceBytes(value) {
  value = resourceNumber(value);
  if (value === null) return '—';
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KiB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(0)} MiB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GiB`;
}
function resourcePercentText(value) { return resourceNumber(value) === null ? '—' : `${Math.round(value)}%`; }
function resourceTaskFromTool(tool) {
  return { create_anima_image: 'anima', create_qwen_image: 'qwen-image-2.1', create_minimax_video: 'minimax-h3', prepare_training: 'lora-preparation' }[tool] || null;
}
function resourceArrays(value) { return Array.isArray(value) ? value : []; }
function resourceTimestamp(value) {
  const date = typeof value === 'string' ? new Date(value) : null;
  return date && Number.isFinite(date.getTime()) ? date : null;
}

// Everything is mounted into the existing isolated shadow root. No page-facing
// IPC bridge, Node integration, external asset, or persistent telemetry is used.
function mountResourceMonitor(shadow, bar, activity, invoke) {
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const style = node('style');
  style.textContent = `
    .resources-toggle{display:flex;align-items:center;gap:5px}.resources-toggle[aria-expanded="true"]{background:#665081;border-color:#c4a1ef}
    .resources-mini{flex-shrink:0;display:flex;gap:9px;align-items:center;padding:0;border:0;background:transparent;font-size:10px;color:#d8cde8}
    .resources-mini:hover{background:transparent;color:#fff}.mini-meter{display:grid;grid-template-columns:auto auto;column-gap:5px;min-width:54px}.mini-meter b{font-weight:500;text-align:right}.mini-track{grid-column:1 / -1;height:3px;background:#4a4258;border-radius:4px;margin-top:3px;overflow:hidden}.mini-track i{display:block;height:100%;background:#bd97f5;transition:width .3s}.resources-mini[data-stale="true"]{opacity:.6}
    .resources-drawer{position:absolute;top:76px;right:0;width:min(420px,100vw);height:calc(100dvh - 76px);box-sizing:border-box;display:flex;flex-direction:column;background:#211e29;border-left:1px solid #685577;box-shadow:-8px 12px 24px #0005;color:#eee9f7;font-size:12px;white-space:normal;isolation:isolate}
    .resources-drawer[hidden]{display:none}.resources-heading{display:flex;align-items:center;justify-content:space-between;padding:15px 17px 10px;border-bottom:1px solid #433b51}.resources-heading h2{font-size:16px;font-weight:650;margin:0}.resources-close{border:0;background:transparent;font-size:20px;padding:0 6px}.resources-scroll{overflow-y:auto;overscroll-behavior:contain;padding:14px 17px 20px;scrollbar-width:thin;scrollbar-color:#6f5a87 transparent;flex:1;min-height:0}.resource-status{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:14px;color:#bdb2d0;font-size:11px}.resource-status[data-error="true"]{color:#ffb7a6}.resource-status .resource-refresh{background:transparent;padding:3px 8px;font-size:11px;border-color:#655773}.resource-section{margin:0 0 19px}.resource-section h3{font-size:12px;color:#c7b4df;font-weight:600;margin:0 0 9px;letter-spacing:.03em}.resource-task-label{display:block;margin-bottom:6px}.resource-task-select{width:100%;padding:8px 10px;border:1px solid #76618a;border-radius:7px;background:#30293c;color:#f0eafb;font:inherit}.resource-task-select:focus-visible,button:focus-visible{outline:2px solid #d9b8ff;outline-offset:2px}.resource-task-card{margin-top:10px;background:#2d2737;border:1px solid #51435f;border-radius:9px;padding:12px}.resource-task-title{font-size:14px;font-weight:600;margin-bottom:9px}.resource-note{font-size:11px;line-height:1.55;color:#baafca;margin:8px 0 0}.resource-requirements{display:grid;grid-template-columns:1fr 1fr;gap:8px}.resource-need{padding:8px;background:#211d2a;border-radius:6px}.resource-need span{display:block;font-size:10px;color:#b8aac9;margin-bottom:4px}.resource-need strong{display:block;font-size:12px;font-weight:550}.resource-need small{display:block;font-size:10px;margin-top:4px;color:#b8aac9}.resource-detail-list{list-style:none;padding:0;margin:8px 0 0;line-height:1.5;font-size:11px;color:#c9bed9}.resource-detail-list li{margin-top:4px}.resource-test-pc{margin-top:9px;padding-top:9px;border-top:1px solid #54465f;color:#cbbadf;font-size:11px;line-height:1.5}.resource-basis{margin-top:9px;color:#b8aac9;font-size:10px}.resource-basis summary{cursor:pointer}.resource-basis ul{padding-left:16px;margin:5px 0}.resource-card{margin-bottom:9px;padding:11px 12px;background:#292431;border:1px solid #463d52;border-radius:8px}.resource-card-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}.resource-card-heading strong{font-size:12px;font-weight:550;overflow-wrap:anywhere}.resource-card-heading b{font-size:14px;font-weight:550;color:#f3e5ff;flex-shrink:0}.resource-track{height:7px;background:#494050;border-radius:8px;overflow:hidden;position:relative}.resource-fill{display:block;height:100%;background:#b18ada;border-radius:8px;transition:width .3s}.resource-fill[data-pressure="high"]{background:#f8b17d}.resource-fill[data-pressure="critical"]{background:#ee8795}.resource-caption{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:#b9aec9;margin-top:6px}.resource-caption span:last-child{text-align:right}.resource-submetric{display:flex;justify-content:space-between;gap:10px;margin:0 0 8px;color:#bbaccd;font-size:10px}.resource-empty{color:#bcaecd;padding:10px 0;font-size:11px}.resource-runtime{border:1px solid #5a486d;border-radius:7px;padding:10px 12px;background:#30283c;line-height:1.5;margin-bottom:10px}.resource-runtime strong{display:block;font-size:12px;font-weight:550}.resource-runtime p{margin:4px 0 0;font-size:11px;color:#c9badb}.resource-warnings{font-size:11px;line-height:1.5;color:#ffcab0;margin:0;padding-left:15px}.resource-footer{font-size:10px;line-height:1.55;color:#a89bb9;border-top:1px solid #463b53;padding-top:10px}
    @media(max-width:940px){.scope{display:none}.resources-mini{gap:6px}.mini-meter{min-width:48px}.receipt{max-width:28%}}
  `;
  const toggle = node('button', 'resources-toggle', 'PCリソース');
  toggle.type = 'button'; toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-controls', 'local-studio-resources');
  const mini = node('button', 'resources-mini');
  mini.type = 'button'; mini.setAttribute('aria-label', 'PCリソースの詳細を開く'); mini.setAttribute('aria-expanded', 'false'); mini.setAttribute('aria-controls', 'local-studio-resources');
  const miniMeters = {};
  for (const key of ['CPU', 'RAM', 'VRAM']) {
    const meter = node('span', 'mini-meter');
    const label = node('span', '', key); const value = node('b', '', '—');
    const track = node('span', 'mini-track'); const fill = node('i'); fill.style.width = '0%'; track.append(fill);
    meter.append(label, value, track); mini.append(meter); miniMeters[key] = { value, fill };
  }
  mini.title = '測定中。VRAMはGPUごとの使用率の最大値です。';
  const drawer = node('section', 'resources-drawer'); drawer.id = 'local-studio-resources'; drawer.hidden = true;
  drawer.setAttribute('aria-label', 'PCリソース');
  const heading = node('div', 'resources-heading'); const title = node('h2', '', 'PCリソース');
  const close = node('button', 'resources-close', '×'); close.type = 'button'; close.setAttribute('aria-label', 'PCリソースを閉じる'); heading.append(title, close);
  const scroll = node('div', 'resources-scroll');
  const status = node('div', 'resource-status'); const statusText = node('span', '', '測定中…');
  const refresh = node('button', 'resource-refresh', '更新'); refresh.type = 'button'; status.append(statusText, refresh);
  const tasksSection = node('section', 'resource-section'); const taskLabel = node('label', 'resource-task-label', 'タスクに必要なリソース');
  const taskSelect = node('select', 'resource-task-select'); taskSelect.id = 'local-studio-resource-task'; taskLabel.setAttribute('for', taskSelect.id);
  const autoOption = node('option', '', '自動 · 現在の作業'); autoOption.value = 'auto'; taskSelect.append(autoOption);
  const taskCard = node('div', 'resource-task-card'); taskCard.append(node('div', 'resource-empty', 'タスク情報を確認中…'));
  tasksSection.append(taskLabel, taskSelect, taskCard);
  const runtime = node('div', 'resource-runtime'); runtime.hidden = true;
  const measuredSection = node('section', 'resource-section'); measuredSection.append(node('h3', '', '使用中のリソース · PC全体'));
  const metrics = node('div'); metrics.append(node('div', 'resource-empty', '測定中…')); measuredSection.append(metrics);
  const warnings = node('ul', 'resource-warnings'); warnings.hidden = true;
  const footer = node('p', 'resource-footer', '約3秒ごとに測定します。最小必要量が未測定のタスクは、動作確認PCと設定を参考に表示します。画像・動画生成では会話モデルを解放してGPUを交代使用します。表示は実行可否の保証ではありません。');
  scroll.append(status, tasksSection, runtime, measuredSection, warnings, footer); drawer.append(heading, scroll);
  shadow.append(style, drawer); bar.append(toggle); activity.append(mini);
  let latest = null;
  let activityTask = null;
  let fetching = false;
  let error = false;
  let stopped = false;
  let timer = null;
  let knownOptions = '';
  let taskDetailsOpen = false;
  let renderedTaskKey = '';
  const setOpen = value => {
    drawer.hidden = !value; toggle.setAttribute('aria-expanded', String(value)); mini.setAttribute('aria-expanded', String(value));
    if (value) { close.focus(); refreshResources(); }
    else toggle.focus();
  };
  toggle.addEventListener('click', () => setOpen(drawer.hidden)); mini.addEventListener('click', () => setOpen(drawer.hidden));
  close.addEventListener('click', () => setOpen(false));
  shadow.addEventListener('keydown', event => { if (event.key === 'Escape' && !drawer.hidden) { event.preventDefault(); setOpen(false); } });
  function displayStatus() {
    const measured = resourceTimestamp(latest?.timestamp);
    const stale = !!measured && Date.now() - measured.getTime() > 15000;
    const time = measured ? measured.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
    statusText.textContent = error ? `更新失敗${time ? ` · 最終測定 ${time}` : ' · 再接続を確認中'}` : fetching ? `更新中${time ? ` · 前回 ${time}` : '…'}` : stale ? `更新待ち · 最終測定 ${time}` : `測定 ${time || '—'}`;
    status.dataset.error = String(error);
    mini.dataset.stale = String(error || stale);
    refresh.disabled = fetching;
    mini.title = `${statusText.textContent}。VRAMはGPUごとの使用率の最大値です。`;
  }
  function meterCard(label, used, total, free, percent, subtitle) {
    percent = resourcePercent(used, total, percent);
    const card = node('div', 'resource-card'); const top = node('div', 'resource-card-heading');
    top.append(node('strong', '', label), node('b', '', resourcePercentText(percent))); card.append(top);
    if (subtitle) card.append(node('div', 'resource-submetric', subtitle));
    const track = node('div', 'resource-track'); track.setAttribute('role', 'meter'); track.setAttribute('aria-label', `${label}の使用率`); track.setAttribute('aria-valuemin', '0'); track.setAttribute('aria-valuemax', '100');
    if (percent !== null) track.setAttribute('aria-valuenow', String(Math.round(percent)));
    else track.setAttribute('aria-valuetext', '未取得');
    const fill = node('span', 'resource-fill'); fill.style.width = `${percent ?? 0}%`; fill.dataset.pressure = percent >= 95 ? 'critical' : percent >= 85 ? 'high' : 'normal'; track.append(fill); card.append(track);
    const caption = node('div', 'resource-caption');
    caption.append(node('span', '', total === undefined ? 'PC全体の使用率' : `使用 ${resourceBytes(used)} / ${resourceBytes(total)}`), node('span', '', free === undefined ? '' : `空き ${resourceBytes(free)}`)); card.append(caption);
    return card;
  }
  function renderMeasurements(value) {
    metrics.replaceChildren();
    metrics.append(meterCard('CPU', undefined, undefined, undefined, value.cpu?.percent, resourceNumber(value.cpu?.logicalCores) === null ? '' : `${value.cpu.logicalCores} 論理コア`));
    const memory = value.memory || {};
    metrics.append(meterCard('RAM', memory.usedBytes, memory.totalBytes, memory.availableBytes, memory.percent));
    const gpus = resourceArrays(value.gpus);
    if (!gpus.length) metrics.append(node('div', 'resource-empty', 'GPU情報は取得できません。未取得を空きとは扱いません。'));
    for (const gpu of gpus) {
      const utilization = resourcePercentText(resourcePercent(null, null, gpu.utilizationPercent));
      const temperature = resourceNumber(gpu.temperatureC);
      metrics.append(meterCard(gpu.name || 'GPU', gpu.memoryUsedBytes, gpu.memoryTotalBytes, gpu.memoryFreeBytes, null, `GPU稼働 ${utilization}${temperature === null ? '' : ` · ${Math.round(temperature)}℃`} · VRAM`));
    }
    const disks = resourceArrays(value.disks);
    if (!disks.length) metrics.append(node('div', 'resource-empty', 'ディスク情報は未取得です。'));
    for (const disk of disks) metrics.append(meterCard(`ディスク · ${disk.label || '保存先'}`, disk.usedBytes, disk.totalBytes, disk.freeBytes, disk.percent));
    const vramPercents = gpus.map(gpu => resourcePercent(gpu.memoryUsedBytes, gpu.memoryTotalBytes, null)).filter(percent => percent !== null);
    const miniValues = { CPU: resourcePercent(null, null, value.cpu?.percent), RAM: resourcePercent(memory.usedBytes, memory.totalBytes, memory.percent), VRAM: vramPercents.length ? Math.max(...vramPercents) : null };
    for (const [key, percent] of Object.entries(miniValues)) { miniMeters[key].value.textContent = resourcePercentText(percent); miniMeters[key].fill.style.width = `${percent ?? 0}%`; }
    runtime.replaceChildren();
    const active = value.active || {};
    if (active.modelLabel || active.usage) {
      runtime.hidden = false;
      const activeText = { running: '実行中', queued: '待機ジョブあり', idle: '待機中', unknown: '状態未取得' }[active.state] || '状態未取得';
      const loadedText = active.modelLoaded === true ? '読み込み済み' : active.modelLoaded === false ? '未読み込み' : '読込状態未取得';
      runtime.append(node('strong', '', `会話モデル: ${active.modelLabel || '未取得'}（${loadedText}）`));
      runtime.append(node('p', '', `PC全体のタスク · ${activeText}`));
      const usage = active.usage || {};
      runtime.append(node('p', '', `会話エンジン実測RAM ${resourceBytes(usage.memoryBytes)}${resourceNumber(usage.processCount) === null ? '' : ` · ${usage.processCount} プロセス`}`));
      runtime.append(node('p', '', '最低必要量ではありません。共有ページを含む合計です。GPU専有量は未取得のため、PC全体のVRAMと分けて表示しています。'));
      const counts = [];
      for (const [field, label] of [['inferenceRequests', '推論'], ['runningJobs', '画像・動画実行'], ['queuedJobs', '画像・動画待機'], ['pendingAgentJobs', 'エージェント待機']]) {
        const count = resourceNumber(active[field]); if (count !== null) counts.push(`${label} ${count}件`);
      }
      if (counts.length) runtime.append(node('p', '', counts.join(' · ')));
    } else runtime.hidden = true;
    warnings.replaceChildren();
    for (const warning of resourceArrays(value.warnings)) if (typeof warning === 'string') warnings.append(node('li', '', warning));
    warnings.hidden = !warnings.childElementCount;
  }
  function renderTask() {
    if (!latest) return;
    const tasks = resourceArrays(latest.tasks);
    const optionsKey = tasks.map(task => `${task.id}:${task.label}`).join('|');
    if (optionsKey !== knownOptions) {
      const previous = taskSelect.value;
      taskSelect.replaceChildren(autoOption);
      for (const task of tasks) { const option = node('option', '', task.label || task.id); option.value = task.id; taskSelect.append(option); }
      taskSelect.value = tasks.some(task => task.id === previous) ? previous : 'auto'; knownOptions = optionsKey;
    }
    const suggested = activityTask || latest.active?.taskId || (latest.active?.state === 'idle' && latest.active?.modelLoaded === true ? 'swift-flash-next' : null);
    const task = tasks.find(item => item.id === (taskSelect.value === 'auto' ? suggested : taskSelect.value));
    const taskKey = JSON.stringify([task || null, !!tasks.length, latest.memory?.totalBytes, resourceArrays(latest.gpus).map(gpu => gpu.memoryTotalBytes)]);
    if (taskKey === renderedTaskKey) return;
    renderedTaskKey = taskKey;
    taskCard.replaceChildren();
    if (!task) { taskCard.append(node('div', 'resource-empty', tasks.length ? '実行対象は判別できません。タスクを選んで目安を確認できます。' : 'タスク情報は未取得です。')); return; }
    const taskDetails = node('details');
    taskDetails.open = taskDetailsOpen;
    const summary = node('summary', 'resource-task-title', `${task.label || task.id} · 必要目安を見る`);
    taskDetails.append(summary);
    taskDetails.addEventListener('toggle', () => { taskDetailsOpen = taskDetails.open; });
    taskCard.append(taskDetails);
    const requirements = task.requirements || {};
    const grid = node('div', 'resource-requirements');
    const gpuCapacities = resourceArrays(latest.gpus).map(gpu => resourceNumber(gpu.memoryTotalBytes)).filter(value => value !== null);
    const maximumVram = gpuCapacities.length ? Math.max(...gpuCapacities) : null;
    for (const [field, label, capacity] of [['memoryBytes', '必要RAM', latest.memory?.totalBytes], ['gpuMemoryBytes', '必要VRAM', maximumVram], ['additionalDiskBytes', '追加ディスク', null], ['modelStorageBytes', '重み保存容量', null]]) {
      const need = node('div', 'resource-need'); const amount = resourceNumber(requirements[field]);
      need.append(node('span', '', label), node('strong', '', amount === null ? field === 'modelStorageBytes' ? '未取得' : '未測定' : resourceBytes(amount)));
      if (field === 'memoryBytes' || field === 'gpuMemoryBytes') need.append(node('small', '', `搭載 ${resourceBytes(capacity)}`));
      if (field === 'modelStorageBytes') need.append(node('small', '', 'RAM使用量とは異なります'));
      grid.append(need);
    }
    taskDetails.append(grid);
    if (resourceNumber(requirements.memoryBytes) === null || resourceNumber(requirements.gpuMemoryBytes) === null) taskDetails.append(node('p', 'resource-note', '必要容量は設定・入力・解像度で変わります。最低必要量は未測定です。'));
    const configs = [];
    if (resourceNumber(requirements.contextTokens) !== null) configs.push(`コンテキスト ${requirements.contextTokens.toLocaleString('ja-JP')} tokens`);
    if (resourceNumber(requirements.vramReserveBytes) !== null) configs.push(`GPU空き予約 ${resourceBytes(requirements.vramReserveBytes)}`);
    if (task.configured) {
      if (resourceNumber(task.configured.width) !== null && resourceNumber(task.configured.height) !== null) configs.push(`${task.configured.width} × ${task.configured.height}`);
      if (resourceNumber(task.configured.frames) !== null) configs.push(`${task.configured.frames} フレーム`);
      if (resourceNumber(task.configured.batchSize) !== null) configs.push(`バッチ ${task.configured.batchSize}`);
    }
    if (configs.length) taskDetails.append(node('p', 'resource-note', `現在の設定 · ${configs.join(' · ')}`));
    const tested = task.testedOn;
    if (tested) {
      const checked = node('div', 'resource-test-pc');
      checked.append(node('div', '', '動作確認PC（最低要件ではありません）'), node('div', '', `${tested.gpuLabel || 'GPU'} · VRAM ${resourceBytes(tested.vramBytes)} · RAM ${resourceBytes(tested.ramBytes)}`));
      taskDetails.append(checked);
    }
    const notes = node('ul', 'resource-detail-list');
    for (const note of resourceArrays(task.notes)) if (typeof note === 'string') notes.append(node('li', '', note));
    if (notes.childElementCount) taskDetails.append(notes);
    const basis = resourceArrays(task.basis).filter(item => typeof item === 'string');
    if (basis.length) {
      const section = node('details', 'resource-basis'); section.append(node('summary', '', '目安の根拠')); const list = node('ul');
      basis.forEach(item => list.append(node('li', '', item))); section.append(list); taskDetails.append(section);
    }
  }
  taskSelect.addEventListener('change', renderTask);
  async function refreshResources() {
    if (fetching || stopped || document.hidden) return;
    fetching = true; displayStatus();
    try {
      const value = await invoke();
      if (!value || value.schemaVersion !== 1 || !resourceTimestamp(value.timestamp)) throw new Error('Invalid resource snapshot');
      if (stopped) return;
      latest = value; error = false; renderMeasurements(value); renderTask();
    } catch (_) { if (!stopped) error = true; }
    finally { fetching = false; if (!stopped) displayStatus(); }
  }
  refresh.addEventListener('click', refreshResources);
  function schedule() {
    if (timer) clearInterval(timer);
    timer = null;
    if (!stopped && !document.hidden) { refreshResources(); timer = setInterval(refreshResources, 3000); }
  }
  document.addEventListener('visibilitychange', () => { displayStatus(); schedule(); });
  window.addEventListener('pagehide', () => { stopped = true; if (timer) clearInterval(timer); }, { once: true });
  schedule();
  return {
    setActivity(run) {
      const next = run?.active ? resourceTaskFromTool(run.tool) : null;
      if (next !== activityTask) { activityTask = next; renderTask(); }
    }
  };
}

if (location.origin === 'http://127.0.0.1:18081' && process.isMainFrame) {
  if (!localStorage.getItem('locale')) localStorage.setItem('locale', 'ja-JP');
  if (!localStorage.getItem('i18nextLng')) localStorage.setItem('i18nextLng', 'ja-JP');
  if (!localStorage.getItem('sidebar')) localStorage.setItem('sidebar', 'true');
  window.addEventListener('DOMContentLoaded', () => {
    const host = document.createElement('aside');
    host.id = 'local-studio-project-bar';
    host.style.cssText = 'position:fixed;inset:0 0 auto 0;height:76px;z-index:2147483647';
    const shadow = host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = `:host{font-family:system-ui,sans-serif;color:#edeaf6} .bar{display:flex;align-items:center;gap:10px;height:44px;padding:0 12px;box-sizing:border-box;background:#25232d;border-bottom:1px solid #454052} button{flex-shrink:0;background:#403751;color:#fff;border:1px solid #756286;border-radius:6px;padding:5px 10px;font:inherit;font-size:12px;cursor:pointer} button:hover{background:#59476f} button:disabled{opacity:.5;cursor:wait} .path{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;flex:1} .scope{font-size:11px;color:#bdb6ca;white-space:nowrap}`;
    const bar = document.createElement('div'); bar.className = 'bar';
    const choose = document.createElement('button'); choose.textContent = 'フォルダを選択';
    const label = document.createElement('span'); label.className = 'path'; label.textContent = '作業フォルダを確認中…';
    const scope = document.createElement('span'); scope.className = 'scope'; scope.textContent = '全チャット共通';
    const open = document.createElement('button'); open.textContent = '開く';
    const reset = document.createElement('button'); reset.textContent = '標準へ戻す';
    bar.append(choose, label, scope, open, reset); shadow.append(style, bar);
    style.textContent += ' .activity{height:32px;box-sizing:border-box;display:flex;align-items:center;gap:12px;padding:0 12px;background:#1d1b23;color:#c8c1d2;font-size:12px;white-space:nowrap;overflow:hidden} .state{font-weight:600;color:#b9a1ed}.state[data-active="true"]::before{content:"● ";color:#bca0fa} .state[data-error="true"]{color:#ffb0a7}.detail{overflow:hidden;text-overflow:ellipsis;flex:1}.receipt{max-width:42%;overflow:hidden;text-overflow:ellipsis;color:#dbc4fb}';
    const activity = document.createElement('div'); activity.className = 'activity';
    const state = document.createElement('span'); state.className = 'state'; state.setAttribute('role', 'status');
    const detail = document.createElement('span'); detail.className = 'detail';
    const receipt = document.createElement('span'); receipt.className = 'receipt'; receipt.setAttribute('role', 'status');
    activity.append(state, detail, receipt); shadow.append(activity);
    const resources = mountResourceMonitor(shadow, bar, activity, () => ipcRenderer.invoke('resources:status'));
    const phases = {preparing:'送信準備中',thinking:'モデルの応答待ち',generating:'応答中',tool:'ツール実行中',approval:'承認待ち',stopping:'停止処理中',stopped:'停止しました',completed:'完了',error:'エラー'};
    const tools = {current_project:'作業先の確認',list_workspace:'ファイル一覧',search_workspace:'ファイル検索',read_workspace_file:'ファイル読取',write_workspace_file:'ファイル保存',run_powershell:'コマンド実行',create_anima_image:'Anima画像生成',create_qwen_image:'Qwen画像生成',create_minimax_video:'MiniMax動画生成',open_workspace_image:'画像読取'};
    const receipts = new Map();
    const chatId = () => location.pathname.startsWith('/c/') ? decodeURIComponent(location.pathname.slice(3)) : '';
    window.addEventListener('local-studio-queue', event => {
      const value = event.detail;
      if (!value || typeof value.chatId !== 'string') return;
      const descriptions = {stopping:'追加指示を受付・停止完了を待機中',sending:'追加指示を送信中',sent:'追加指示の再開要求を送信しました',retained:'追加指示は元のチャットの待機欄に保持',error:'追加指示の送信でエラー・待機欄とチャットを確認'};
      if (descriptions[value.state]) receipts.set(value.chatId, descriptions[value.state]);
      receipt.textContent = receipts.get(chatId()) || '';
    });
    let checking = false;
    async function refreshActivity() {
      if (checking) return;
      checking = true;
      const chat = chatId();
      receipt.textContent = receipts.get(chat) || '';
      try {
        const token = localStorage.getItem('token');
        if (!token) { state.textContent = '接続準備中'; detail.textContent = ''; return; }
        const response = await fetch('/api/local-studio/activity?chat_id=' + encodeURIComponent(chat), { headers: { Authorization: 'Bearer ' + token }, cache: 'no-store', signal: AbortSignal.timeout(5000) });
        if (!response.ok) throw new Error('activity unavailable');
        const value = await response.json();
        if (chat !== chatId()) return;
        const run = value.state;
        resources.setActivity(run);
        state.textContent = run ? (phases[run.phase] || '状態を確認中') : '待機中';
        state.dataset.active = String(!!run?.active); state.dataset.error = String(run?.phase === 'error');
        detail.textContent = run ? [run.tool ? (tools[run.tool] || run.tool) : '', run.active ? `経過 ${run.elapsed_seconds}秒・状態更新 ${run.quiet_seconds}秒前` : '', run.phase === 'stopping' ? '実行中の操作が終わるまでお待ちください' : run.error, run.active && run.quiet_seconds >= 60 ? '更新がしばらくありません' : ''].filter(Boolean).join(' · ') : value.active_count ? `別のチャットで ${value.active_count}件が実行中` : 'メッセージを送ると作業を開始します';
        detail.title = detail.textContent;
      } catch (_) {
        state.textContent = '接続を確認できません'; state.dataset.active = 'false'; state.dataset.error = 'true';
        detail.textContent = '処理が停止したとは限りません。再接続を確認中…';
      } finally { checking = false; }
    }
    refreshActivity();
    setInterval(refreshActivity, 1500);
    const pageStyle = document.createElement('style');
    pageStyle.textContent = 'html,body{height:100%!important;overflow:hidden!important}body>div[style*="display: contents"]{display:block!important;position:absolute!important;inset:76px 0 0!important;transform:translateZ(0);height:calc(100dvh - 76px)!important}body .h-screen,body .h-dvh,body [class~="h-[100dvh]"]{height:calc(100dvh - 76px)!important}body .min-h-screen,body .min-h-dvh,body [class~="min-h-[100dvh]"]{min-height:calc(100dvh - 76px)!important}';
    document.head.append(pageStyle); document.body.append(host);
    function display(value) {
      label.textContent = value.error || value.path;
      label.title = value.error || value.path;
      open.disabled = !!value.error;
    }
    async function act(channel) {
      choose.disabled = reset.disabled = true;
      try { const value = await ipcRenderer.invoke(channel); if (value) display(value); }
      catch (error) { display({ error: error.message }); }
      finally { choose.disabled = reset.disabled = false; }
    }
    choose.addEventListener('click', () => act('project:choose'));
    open.addEventListener('click', () => act('project:open'));
    reset.addEventListener('click', () => act('project:reset'));
    ipcRenderer.on('project:changed', (_event, value) => display(value));
    act('project:info');
  });
}
