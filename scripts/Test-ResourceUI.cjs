// Offline behavior checks and an explicitly synthetic visual fixture. No models
// start, no hardware is queried, and no application/history files are touched.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const preloadPath = path.join(__dirname, '..', 'desktop', 'preload.cjs');
const preload = fs.readFileSync(preloadPath, 'utf8');
const GiB = 1024 ** 3;

function sample() {
  const testedOn = { gpuLabel: 'NVIDIA GeForce RTX 4090', vramBytes: 24 * GiB, ramBytes: 158 * GiB };
  const requirements = { memoryBytes: null, gpuMemoryBytes: null, additionalDiskBytes: null, modelStorageBytes: 72 * GiB, contextTokens: 131072, vramReserveBytes: 1.5 * GiB };
  return {
    schemaVersion: 1, timestamp: new Date().toISOString(),
    cpu: { percent: 17, logicalCores: 32 },
    memory: { totalBytes: 158 * GiB, usedBytes: 94 * GiB, availableBytes: 64 * GiB, percent: 59.5 },
    gpus: [{ name: 'NVIDIA GeForce RTX 4090', utilizationPercent: 32, memoryTotalBytes: 24 * GiB, memoryUsedBytes: 19.8 * GiB, memoryFreeBytes: 4.2 * GiB, temperatureC: 52 }],
    disks: [{ label: 'C: / AI', totalBytes: 1000 * GiB, usedBytes: 530 * GiB, freeBytes: 470 * GiB, percent: 53 }],
    tasks: [
      { id: 'swift-flash-next', label: 'Swift · 会話 / 画像理解', kind: 'inference', requirements, testedOn, basis: ['表示確認用の合成データです。実機測定ではありません。'], notes: ['128Kは設定値です。入力全量でのメモリ消費量は未測定です。'] },
      { id: 'anima', label: 'Anima · 画像生成', kind: 'image', requirements: { ...requirements, modelStorageBytes: 8 * GiB, contextTokens: null, vramReserveBytes: null }, testedOn, configured: { width: 512, height: 512, batchSize: 1 }, basis: ['表示確認用の合成データです。'], notes: ['会話モデルを解放し、GPUを交代使用します。'] },
      { id: 'qwen-image-2.1', label: 'Qwen Image 2.1 · 画像生成', kind: 'image', requirements: { ...requirements, modelStorageBytes: 20 * GiB, contextTokens: null }, testedOn, notes: ['解像度や参照枚数で使用量が変わります。'] },
      { id: 'minimax-h3', label: 'MiniMax H3 · 動画生成', kind: 'video', requirements: { ...requirements, contextTokens: null }, testedOn, configured: { width: 832, height: 480, frames: 33, batchSize: 1 }, notes: ['フレーム数によって使用量が変わります。'] },
      { id: 'lora-preparation', label: 'LoRA · 学習の準備', kind: 'preparation', requirements: { memoryBytes: null, gpuMemoryBytes: null, additionalDiskBytes: null, modelStorageBytes: null }, testedOn: null, notes: ['資料・設定を準備する導線です。学習は実行しません。'] }
    ],
    active: { taskId: 'swift-flash-next', modelLabel: 'Swift 1.5 Flash Next', backend: 'strata', modelLoaded: true, state: 'idle', inferenceRequests: 0, pendingAgentJobs: 0, runningJobs: 0, queuedJobs: 0, usage: { memoryBytes: 68 * GiB, processCount: 3, gpuMemoryBytes: null, basis: '合成データ' } },
    warnings: []
  };
}

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.attributes = {}; this.listeners = new Map(); this._text = ''; this._value = ''; this.hidden = false; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  get childElementCount() { return this.children.length; }
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
  append(...children) { this.children.push(...children); if (this.tagName === 'select' && !this._value && this.children.length) this._value = this.children[0].value; }
  replaceChildren(...children) { this._text = ''; this.children = []; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(name, listener) { if (!this.listeners.has(name)) this.listeners.set(name, []); this.listeners.get(name).push(listener); }
  fire(name, value = {}) { for (const listener of this.listeners.get(name) || []) listener(value); }
  focus() { this.focused = true; }
}
function find(root, predicate) {
  if (predicate(root)) return root;
  for (const child of root.children) { const result = find(child, predicate); if (result) return result; }
  return null;
}
function environment() {
  const document = new Element('document'); document.createElement = tag => new Element(tag); document.hidden = false;
  const window = new Element('window'); const intervals = new Map(); let sequence = 0;
  const context = vm.createContext({ require: name => { assert.equal(name, 'electron'); return { ipcRenderer: {} }; }, document, window, location: { origin: 'https://fixture.invalid' }, process: { isMainFrame: true }, Date, setInterval: callback => { const id = ++sequence; intervals.set(id, callback); return id; }, clearInterval: id => intervals.delete(id) });
  vm.runInContext(preload, context, { filename: preloadPath });
  return { context, document, window, intervals };
}
const settle = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

async function test() {
  const env = environment(); const helpers = env.context;
  for (const value of [null, undefined, '12', -1, NaN, Infinity]) assert.equal(helpers.resourceNumber(value), null);
  assert.equal(helpers.resourceNumber(0), 0);
  assert.equal(helpers.resourcePercent(null, null, null), null);
  assert.equal(helpers.resourcePercent(0, 100, null), 0);
  assert.equal(helpers.resourcePercent(120, 100, null), 100);
  assert.equal(helpers.resourcePercent(1, 0, null), null);
  assert.equal(helpers.resourceBytes(null), '—');
  assert.equal(helpers.resourceBytes(2 * GiB), '2.0 GiB');
  assert.equal(helpers.resourceTaskFromTool('create_qwen_image'), 'qwen-image-2.1');
  assert.equal(helpers.resourceTaskFromTool('read_workspace_file'), null);

  const shadow = new Element('shadow'); const bar = new Element('div'); const activity = new Element('div');
  shadow.append(bar, activity);
  let payload = sample(); let calls = 0; let pending = null;
  const controls = helpers.mountResourceMonitor(shadow, bar, activity, () => {
    calls++;
    return new Promise((resolve, reject) => { pending = { resolve, reject }; });
  });
  assert.equal(calls, 1);
  for (const callback of env.intervals.values()) callback();
  assert.equal(calls, 1, 'overlapping polls must be suppressed');
  const drawer = find(shadow, element => element.className === 'resources-drawer');
  assert.equal(drawer.hidden, true);
  assert.equal(drawer.style?.height, undefined, 'drawer bounds belong to CSS, not the chat layout');
  pending.resolve(payload); await settle();
  const task = find(shadow, element => element.className === 'resource-task-card');
  const select = find(shadow, element => element.tagName === 'select');
  assert.match(task.textContent, /Swift/);
  assert.match(task.textContent, /最低要件ではありません/);
  assert.match(task.textContent, /RAM使用量とは異なります/);
  assert.match(task.textContent, /未測定/);
  assert.ok(!task.textContent.includes('実行可能'), 'display must not promise capacity from unknown minima');
  const runtime = find(shadow, element => element.className === 'resource-runtime');
  assert.match(runtime.textContent, /実測RAM 68.0 GiB/);
  assert.match(runtime.textContent, /共有ページ/);
  controls.setActivity({ active: true, tool: 'create_anima_image' });
  assert.match(task.textContent, /Anima/);
  select.value = 'qwen-image-2.1'; select.fire('change');
  controls.setActivity({ active: true, tool: 'create_minimax_video' });
  assert.match(task.textContent, /Qwen Image/, 'manual task selection must win over current activity');
  select.value = 'auto'; select.fire('change');
  assert.match(task.textContent, /MiniMax/);
  controls.setActivity({ active: false, tool: 'create_minimax_video' });
  assert.match(task.textContent, /Swift/, 'completed media tool must not pin automatic task forever');

  const toggle = find(shadow, element => element.className === 'resources-toggle');
  toggle.fire('click'); assert.equal(drawer.hidden, false); assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  pending.reject(new Error('offline')); await settle();
  const status = find(shadow, element => element.className === 'resource-status');
  assert.match(status.textContent, /更新失敗/);
  assert.match(runtime.textContent, /68.0 GiB/, 'failed refresh must retain the last known measurements');
  assert.equal(find(shadow, element => element.className === 'resources-mini').dataset.stale, 'true');
  shadow.fire('keydown', { key: 'Escape', preventDefault() {} });
  assert.equal(drawer.hidden, true); assert.equal(toggle.focused, true);
  env.document.hidden = true; env.document.fire('visibilitychange');
  assert.equal(env.intervals.size, 0, 'hidden windows must stop polling');
  const hiddenCalls = calls;
  env.document.hidden = false; env.document.fire('visibilitychange');
  assert.equal(calls, hiddenCalls + 1);
  payload = sample(); payload.memory = {}; payload.gpus = []; payload.cpu = {}; payload.warnings = ['測定対象が取得できません'];
  pending.resolve(payload); await settle();
  const mini = find(shadow, element => element.className === 'resources-mini');
  assert.equal(mini.textContent, 'CPU—RAM—VRAM—', 'missing measurements must not become zero');
  assert.match(find(shadow, element => element.className === 'resource-warnings').textContent, /測定対象/);
  for (const callback of env.intervals.values()) callback();
  payload = sample(); payload.active.taskId = null; payload.active.state = 'running'; payload.active.runningJobs = 1;
  pending.resolve(payload); await settle();
  assert.match(task.textContent, /実行対象は判別できません/, 'an unrelated Comfy queue must not imply Swift is running');
  assert.match(runtime.textContent, /Swift 1.5 Flash Next（読み込み済み）/);
  assert.match(runtime.textContent, /PC全体のタスク · 実行中/);
  assert.ok(!runtime.textContent.includes('Swift 1.5 Flash Next · 実行中'));
  select.value = 'anima'; select.fire('change');
  const details = task.children[0]; details.open = true; details.fire('toggle');
  for (const callback of env.intervals.values()) callback();
  pending.resolve(payload); await settle();
  assert.equal(task.children[0].open, true, 'polling must retain requirement expansion');
  payload.timestamp = new Date(Date.now() - 30000).toISOString();
  for (const callback of env.intervals.values()) callback();
  pending.resolve(payload); await settle();
  assert.match(status.textContent, /更新待ち · 最終測定/);
  env.window.fire('pagehide'); assert.equal(env.intervals.size, 0);
  assert.equal((preload.match(/ipcRenderer\.invoke\('resources:status'\)/g) || []).length, 1);
  assert.ok(!preload.includes('contextBridge.exposeInMainWorld'));
  process.stdout.write('PASS: missing measurements, bars, overlap, task selection, stale values, drawer, visibility, fixed IPC.\n');
}

function writeFixture(destination) {
  const fixturePreload = preload.replace("attachShadow({ mode: 'closed' })", "attachShadow({ mode: 'open' })");
  const initial = sample(); initial.warnings = ['UI表示確認用の合成データです。実機測定ではありません。'];
  const fake = `const process={isMainFrame:true}; const location={origin:'http://127.0.0.1:18081',pathname:'/'}; const localStorage={getItem:()=>null,setItem:()=>{}}; const require=()=>({ipcRenderer:{invoke:async channel=>channel==='resources:status'?${JSON.stringify(initial)}:{path:'C:/作業/サンプル'},on:()=>{}}});`;
  const html = `<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PCリソース UI表示確認用</title><style>body{margin:0;background:#17151b;color:#d6cce3;font:14px system-ui}.fixture-chat{position:fixed;top:76px;left:0;right:420px;bottom:0;padding:30px;overflow:auto}.fixture-bubble{padding:16px;background:#302b3a;border-radius:14px;margin:20px 0}.fixture-info{color:#ac94c6;font-size:12px}.fixture-input{position:absolute;bottom:25px;left:30px;right:30px;border:1px solid #5f526e;border-radius:16px;padding:14px}.fixture-sidebar{position:fixed;top:76px;bottom:0;left:0;width:175px;background:#211e29;padding:18px;box-sizing:border-box}.fixture-chat{left:175px}@media(max-width:900px){.fixture-sidebar{display:none}.fixture-chat{left:0;right:420px;padding:15px}}</style><body><aside class="fixture-sidebar">Local Studio<br><br>＋ 新しいチャット<br><br>今日<br>リソースUIの確認</aside><main class="fixture-chat"><p class="fixture-info">UI表示確認用の合成データです · 実機測定ではありません</p><h2>リソースを確認しながら作業</h2><div class="fixture-bubble">どのタスクにどれくらいの容量を使うか、右のパネルで確認できます。</div><p>必要量が未測定の値は0に置き換えません。動作確認PCと現在の使用量を分けて表示します。</p><div class="fixture-input">メッセージを送信…</div></main><script>(()=>{${fake}\n${fixturePreload}\nwindow.addEventListener('DOMContentLoaded',()=>{document.getElementById('local-studio-project-bar').shadowRoot.querySelector('.resources-toggle').click();});})();<\/script></body></html>`;
  fs.mkdirSync(path.dirname(path.resolve(destination)), { recursive: true });
  fs.writeFileSync(destination, html, 'utf8');
  process.stdout.write(`Fixture written: ${path.resolve(destination)}\n`);
}
if (process.argv[2] === '--write-fixture' && process.argv[3]) writeFixture(process.argv[3]);
else test().catch(error => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
