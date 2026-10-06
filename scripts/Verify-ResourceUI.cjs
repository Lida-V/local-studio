// Run the unchanged source preload in an independent, hidden Electron fixture.
// Every HTTP response and IPC result is synthetic. Never launch the real app.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const support = path.resolve(__dirname, '..');
const GiB = 1024 ** 3;
function options(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    if (!['--electron', '--playwright', '--output'].includes(key) || !argv[index + 1]) {
      throw new Error('Use --electron EXE --playwright MODULE_OR_DIRECTORY [--output DIRECTORY].');
    }
    result[key.slice(2)] = argv[index + 1];
  }
  return result;
}
function fixture() {
  const requirements = { memoryBytes: null, gpuMemoryBytes: null, additionalDiskBytes: null,
    modelStorageBytes: 72 * GiB, contextTokens: 131072, vramReserveBytes: 1.5 * GiB };
  const testedOn = { gpuLabel: 'NVIDIA GeForce RTX 4090', vramBytes: 24 * GiB, ramBytes: 160 * GiB };
  return {
    schemaVersion: 1, timestamp: new Date().toISOString(),
    cpu: { percent: 18, logicalCores: 32 },
    memory: { totalBytes: 160 * GiB, usedBytes: 96 * GiB, availableBytes: 64 * GiB, percent: 60 },
    gpus: [{ name: 'NVIDIA GeForce RTX 4090', utilizationPercent: 33, temperatureC: 52,
      memoryTotalBytes: 24 * GiB, memoryUsedBytes: 20 * GiB, memoryFreeBytes: 4 * GiB }],
    disks: [{ label: 'AI保存先', totalBytes: 1000 * GiB, usedBytes: 550 * GiB,
      freeBytes: 450 * GiB, percent: 55 }],
    tasks: [
      { id: 'swift-flash-next', label: 'Swift · 会話 / 画像理解', kind: 'inference', requirements, testedOn,
        notes: ['128Kは設定値です。合成表示テストです。'], basis: ['合成データ。実機測定ではありません。'] },
      { id: 'anima', label: 'Anima · 画像生成', kind: 'image', requirements: { ...requirements,
        modelStorageBytes: 8 * GiB, contextTokens: null, vramReserveBytes: null }, testedOn,
        configured: { width: 512, height: 512, batchSize: 1 }, notes: ['会話モデルを解放してGPUを交代使用します。'] },
      { id: 'lora-preparation', label: 'LoRA · 学習の準備', kind: 'preparation', testedOn: null,
        requirements: { memoryBytes: null, gpuMemoryBytes: null, additionalDiskBytes: null, modelStorageBytes: null },
        notes: ['学習は実行しません。必要量は未測定です。'] }
    ],
    active: { taskId: 'swift-flash-next', modelLabel: 'Swift 1.5 Flash Next', backend: 'strata',
      modelLoaded: true, state: 'idle', inferenceRequests: 0, pendingAgentJobs: 0, runningJobs: 0, queuedJobs: 0,
      usage: { memoryBytes: 68 * GiB, processCount: 3, gpuMemoryBytes: null, basis: '合成データ' } },
    warnings: []
  };
}

// Serialized into a newly-created fixture application, never the product main.
function fixtureMain() {
  const { app, BrowserWindow, session, ipcMain } = require('electron');
  const fs = require('node:fs');
  const path = require('node:path');
  const setup = JSON.parse(fs.readFileSync(path.join(__dirname, 'settings.json'), 'utf8'));
  const log = value => fs.appendFileSync(path.join(__dirname, 'startup.log'), String(value) + '\n');
  log('fixture main loaded');
  process.on('uncaughtException', error => { log(error.stack); app.exit(1); });
  process.on('exit', code => log('fixture exit ' + code));
  const origin = 'http://127.0.0.1:18081';
  const storage = path.join(__dirname, 'profile');
  fs.mkdirSync(storage, { recursive: true });
  fs.writeFileSync(path.join(__dirname, 'owned-pid.json'), JSON.stringify({ pid: process.pid,
    parentPid: process.ppid, script: __filename, created: Date.now() }));
  app.setName('Local Studio Synthetic Resource QA');
  app.setPath('userData', storage);
  app.setPath('sessionData', storage);
  app.setPath('crashDumps', path.join(storage, 'crashes'));
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch('disable-background-networking');
  app.commandLine.appendSwitch('disable-component-update');
  app.commandLine.appendSwitch('lang', 'ja');
  app.commandLine.appendSwitch('force-device-scale-factor', '1');
  global.fixtureState = { mode: 'sample', sample: setup.sample, activity: null,
    resourceCalls: 0, ipcCalls: [], mockedRequests: [], blockedRequests: [] };
  let window;
  app.whenReady().then(async () => {
    log('fixture ready');
    const ownSession = session.fromPartition('resource-ui-qa-' + process.pid, { cache: false });
    ownSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    ownSession.setPermissionCheckHandler(() => false);
    ownSession.setSpellCheckerEnabled(false);
    // This registered HTTP handler returns data directly; no net.fetch/urlopen
    // or HTTP listener is used. Even the original 18081 URL is only virtual.
    ownSession.protocol.handle('http', request => {
      const url = new URL(request.url);
      global.fixtureState.mockedRequests.push(url.pathname);
      if (url.origin !== origin || request.method !== 'GET') return new Response('Blocked', { status: 403 });
      if (url.pathname === '/api/local-studio/activity') {
        return new Response(JSON.stringify({ state: global.fixtureState.activity,
          active_count: global.fixtureState.activity ? 1 : 0 }), { headers: { 'content-type': 'application/json' } });
      }
      if (url.pathname !== '/' && url.pathname !== '/c/synthetic') return new Response('No fixture', { status: 404 });
      return new Response(`<!doctype html><html lang="ja"><head><meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src ${origin}">
        <style>html,body{margin:0;background:#171717;color:#eee;font:14px system-ui,sans-serif}main{height:100%;display:flex}.sidebar{width:220px;background:#202020;padding:24px;box-sizing:border-box}.chat{flex:1;padding:35px;box-sizing:border-box}.sample{max-width:470px;padding:24px;background:#232323;border:1px solid #454545;border-radius:12px}.caption{color:#baa8cf;font-size:12px;line-height:1.7}h1{font-size:22px}textarea{box-sizing:border-box;background:#262626;color:#eee;border:1px solid #555;border-radius:10px;width:100%;height:80px;padding:12px;margin-top:30px}</style>
        <script>localStorage.setItem('token','synthetic-fixture-only');</script></head>
        <body><div style="display: contents"><main><aside class="sidebar"><b>Local Studio</b><p>表示検証</p><p class="caption">合成fixtureのみ<br>会話・制作データなし</p></aside><section class="chat"><h1>PCリソース表示の確認</h1><div class="sample">32論理コア・RAM 160 GiB・RTX 4090 24 GiB<br><p class="caption">すべて架空の数値です。実機リソース測定ではありません。</p></div><textarea aria-label="合成入力" placeholder="このfixtureは送信しません"></textarea></section></main></div></body></html>`,
        { headers: { 'content-type': 'text/html; charset=utf-8' } });
    });
    ownSession.protocol.handle('https', () => new Response('Blocked', { status: 403 }));
    log('fixture protocols mocked');
    ownSession.webRequest.onBeforeRequest((details, callback) => {
      const url = new URL(details.url);
      const allowed = url.protocol === 'http:' && url.origin === origin;
      if (!allowed) global.fixtureState.blockedRequests.push(url.protocol + url.host);
      callback({ cancel: !allowed });
    });
    window = new BrowserWindow({ width: 1280, height: 880, useContentSize: true, frame: false,
      show: false, backgroundColor: '#171717', webPreferences: { session: ownSession,
        preload: setup.preload, contextIsolation: true, nodeIntegration: false, sandbox: true,
        backgroundThrottling: false, spellcheck: false } });
    log('fixture window created');
    window.webContents.on('preload-error', (_event, _file, error) => log(error.stack));
    window.webContents.on('render-process-gone', (_event, details) => log('fixture renderer gone: ' + JSON.stringify(details)));
    const guard = event => {
      if (event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame ||
          new URL(event.senderFrame.url).origin !== origin) throw new Error('Invalid fixture sender');
    };
    ipcMain.handle('project:info', event => { guard(event); global.fixtureState.ipcCalls.push('project:info');
      return { path: 'D:/Synthetic/ResourceUI', source: 'synthetic' }; });
    ipcMain.handle('resources:status', event => {
      guard(event); global.fixtureState.ipcCalls.push('resources:status'); global.fixtureState.resourceCalls++;
      if (global.fixtureState.mode === 'offline') throw new Error('Synthetic resource sampler offline');
      const value = structuredClone(global.fixtureState.sample); value.timestamp = new Date().toISOString();
      if (global.fixtureState.mode === 'missing') {
        value.cpu.percent = null; value.memory = {}; value.gpus = []; value.disks = [];
        value.active = { state: 'unknown', modelLoaded: null, taskId: null };
      }
      return value;
    });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', event => event.preventDefault());
    await window.loadURL(origin + '/c/synthetic');
    log('fixture page loaded');
  }).catch(error => { log(error.stack); console.error(error); app.exit(1); });
  app.on('window-all-closed', () => app.quit());
}

async function main() {
  const args = options(process.argv.slice(2));
  const modulePath = args.playwright || process.env.LOCAL_STUDIO_PLAYWRIGHT || 'playwright';
  const { _electron } = require(modulePath);
  let executablePath = args.electron || process.env.LOCAL_STUDIO_ELECTRON;
  if (!executablePath) {
    const configPath = path.join(support, 'config/support-config.json');
    const example = path.join(support, 'config/support-config.example.json');
    const config = JSON.parse(fs.readFileSync(fs.existsSync(configPath) ? configPath : example, 'utf8').replace(/^\uFEFF/, ''));
    executablePath = path.join(config.target.root, 'apps/local-studio-desktop/node_modules/electron/dist/electron.exe');
  }
  assert(fs.statSync(executablePath).isFile(), 'Supply an installed Electron executable.');
  const output = path.resolve(args.output || path.join(support, 'projects/20261006-ResourceUI/qa'));
  fs.mkdirSync(output, { recursive: true });
  assert.equal(fs.realpathSync(output), output, 'Output directory must not use a link.');
  const run = fs.mkdtempSync(path.join(output, 'electron-'));
  const preload = path.join(support, 'desktop/preload.cjs');
  const hash = () => crypto.createHash('sha256').update(fs.readFileSync(preload)).digest('hex');
  const before = hash();
  const appFolder = path.join(run, 'fixture'); fs.mkdirSync(appFolder);
  fs.writeFileSync(path.join(appFolder, 'settings.json'), JSON.stringify({ preload, sample: fixture() }));
  fs.writeFileSync(path.join(appFolder, 'main.cjs'), '(' + fixtureMain.toString() + ')();\n');
  const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE; delete env.LOCAL_STUDIO_SOURCE;
  const result = { synthetic: true, originalPreload: true, preloadSha256: before, checks: {}, screenshots: [],
    limits: ['Synthetic page and IPC; not the complete Open WebUI interface.', 'Hidden window with background throttling disabled; production visibility suspension is covered separately.'] };
  let app;
  const logs = [];
  try {
    app = await _electron.launch({ executablePath, args: [path.join(appFolder, 'main.cjs')], env, timeout: 20000 });
    app.process().stderr.on('data', data => { if (logs.join('').length < 65536) logs.push(String(data)); });
    const page = await app.firstWindow();
    await page.waitForSelector('#local-studio-project-bar');
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setContentSize(1280, 880));
    // Electron's own debugger avoids a second Playwright renderer CDP session.
    // Only this newly-created fixture webContents is attached.
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.debugger.attach('1.3'));
    const cdp = { send: (method, parameters) => app.evaluate(async ({ BrowserWindow }, request) =>
      BrowserWindow.getAllWindows()[0].webContents.debugger.sendCommand(request.method, request.parameters),
      { method, parameters }) };
    const visit = (node, predicate) => {
      if (predicate(node)) return node;
      for (const child of [...(node.children || []), ...(node.shadowRoots || [])]) { const value = visit(child, predicate); if (value) return value; }
      return null;
    };
    async function nodeId(className) {
      const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true });
      const item = visit(root, node => {
        const attributes = node.attributes || []; const index = attributes.indexOf('class');
        return index >= 0 && attributes[index + 1].split(/\s+/).includes(className);
      });
      assert(item, 'Missing actual preload element: ' + className); return item.nodeId;
    }
    async function on(className, declaration, values = []) {
      const { object } = await cdp.send('DOM.resolveNode', { nodeId: await nodeId(className) });
      try {
        const response = await cdp.send('Runtime.callFunctionOn', { objectId: object.objectId,
          functionDeclaration: declaration, arguments: values.map(value => ({ value })), returnByValue: true });
        if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
        return response.result.value;
      } finally { await cdp.send('Runtime.releaseObject', { objectId: object.objectId }); }
    }
    async function text(className) { return on(className, 'function(){return this.textContent;}'); }
    async function click(className) { return on(className, 'function(){this.click();}'); }
    async function waitFor(check, label) {
      const until = Date.now() + 7000;
      while (Date.now() < until) { if (await check()) return; await new Promise(resolve => setTimeout(resolve, 80)); }
      throw new Error('Timed out: ' + label);
    }
    async function select(value) {
      await on('resource-task-select', 'function(value){this.value=value;this.dispatchEvent(new Event("change",{bubbles:true}));}', [value]);
    }
    async function screenshot(name) {
      const file = name + '.png'; const target = path.join(run, file);
      const viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
      await page.screenshot({ path: target, scale: 'css' });
      const png = fs.readFileSync(target);
      assert.equal(png.readUInt32BE(16), viewport.width, 'Screenshot width must use CSS pixels.');
      assert.equal(png.readUInt32BE(20), viewport.height, 'Screenshot height must use CSS pixels.');
      result.screenshots.push(file);
    }
    await waitFor(async () => await page.evaluate(() => innerWidth === 1280 && innerHeight === 880), 'wide viewport');
    await waitFor(async () => (await text('resources-mini')).includes('18%'), 'initial metrics');
    assert.equal(await page.evaluate(() => location.origin), 'http://127.0.0.1:18081');
    assert.equal(await page.evaluate(() => document.querySelector('#local-studio-project-bar').shadowRoot), null);
    result.checks.originalOriginAndClosedShadow = true;
    await click('resources-toggle');
    await waitFor(async () => !(await on('resources-drawer', 'function(){return this.hidden;}')), 'drawer open');
    assert.match(await text('resource-task-card'), /Swift/); result.checks.autoSwift = true;
    await screenshot('1280-drawer');
    await click('resource-task-title');
    await waitFor(async () => await on('resource-task-card', 'function(){return this.querySelector("details").open;}'), 'requirements expand');
    assert.match(await text('resource-task-card'), /未測定/); result.checks.unknownMinimumNotZero = true;
    await screenshot('1280-requirements');
    await select('lora-preparation'); assert.match(await text('resource-task-card'), /学習の準備/);
    result.checks.manualUnknownTask = true;
    await select('auto');
    await app.evaluate(() => { global.fixtureState.activity = { active: true, phase: 'tool', tool: 'create_anima_image', elapsed_seconds: 4, quiet_seconds: 0 }; });
    await waitFor(async () => (await text('resource-task-card')).includes('Anima'), 'auto activity task');
    result.checks.autoAnimaFromActivity = true;
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setContentSize(760, 600));
    await waitFor(async () => await page.evaluate(() => innerWidth === 760 && innerHeight === 600), 'narrow viewport');
    const geometry = await on('resources-drawer', 'function(){const r=this.getBoundingClientRect();const s=this.querySelector(".resources-scroll");return {left:r.left,right:r.right,bottom:r.bottom,viewport:innerWidth,height:innerHeight,scrollWidth:s.scrollWidth,clientWidth:s.clientWidth};}');
    assert(geometry.left >= 0 && geometry.right <= geometry.viewport + 1 && geometry.bottom <= geometry.height + 1);
    assert(geometry.scrollWidth <= geometry.clientWidth + 1); result.checks.narrowFitsViewport = true;
    await screenshot('760-anima');
    await click('resources-close'); assert.equal(await on('resources-drawer', 'function(){return this.hidden;}'), true);
    await click('resources-toggle'); await page.keyboard.press('Escape');
    await waitFor(async () => await on('resources-drawer', 'function(){return this.hidden;}'), 'Escape close');
    result.checks.closeAndEscape = true;
    await click('resources-toggle');
    const calls = await app.evaluate(() => global.fixtureState.resourceCalls);
    await click('resource-refresh');
    await waitFor(async () => (await app.evaluate(() => global.fixtureState.resourceCalls)) > calls, 'manual refresh');
    result.checks.manualRefresh = true;
    await app.evaluate(() => { global.fixtureState.activity = null; global.fixtureState.mode = 'missing'; });
    await click('resource-refresh');
    await waitFor(async () => (await text('resources-mini')).includes('CPU—'), 'unknown metrics');
    assert.match(await text('resources-drawer'), /GPU情報は取得できません/); result.checks.missingMetricsNotZero = true;
    await screenshot('760-missing');
    await app.evaluate(() => { global.fixtureState.mode = 'offline'; });
    await page.reload(); await page.waitForSelector('#local-studio-project-bar');
    await click('resources-toggle');
    await waitFor(async () => (await text('resource-status')).includes('更新失敗'), 'initial offline');
    assert.match(await text('resources-mini'), /CPU—/); result.checks.offlineInitialUnavailable = true;
    await screenshot('760-offline');
    await app.evaluate(() => { global.fixtureState.mode = 'sample'; });
    await click('resource-refresh');
    await waitFor(async () => (await text('resources-mini')).includes('18%'), 'offline recovery');
    result.checks.offlineRetry = true;
    const state = await app.evaluate(({ app, BrowserWindow }) => ({
      ...global.fixtureState, hidden: BrowserWindow.getAllWindows().every(window => !window.isVisible()),
      userData: app.getPath('userData'), sessionData: app.getPath('sessionData') }));
    assert(state.hidden); assert.equal(state.userData, path.join(appFolder, 'profile')); assert.equal(state.sessionData, state.userData);
    assert(state.mockedRequests.includes('/api/local-studio/activity'));
    assert(state.ipcCalls.every(value => ['project:info', 'resources:status'].includes(value)));
    result.checks.hiddenIsolatedStorageAndSyntheticIPC = true;
    result.network = { mode: 'session.protocol.handle; all other transports denied', mockedPaths: [...new Set(state.mockedRequests)],
      blocked: state.blockedRequests, liveBackendRequests: 0 };
    result.resourceCalls = state.resourceCalls;
    assert.equal(hash(), before, 'Source preload changed during QA; rerun the final source.');
    result.ok = true;
  } catch (error) {
    result.ok = false; result.error = String(error.stack || error);
  } finally {
    if (app) { try { await app.close(); result.fixtureClosed = true; } catch (error) { result.fixtureCloseError = String(error); result.ok = false; } }
    const startup = path.join(appFolder, 'startup.log');
    if (fs.existsSync(startup)) fs.copyFileSync(startup, path.join(run, 'fixture-startup.log'));
    if (result.fixtureClosed) {
      // Remove only this run's own fixture/profile after its Electron exits.
      // Validate the absolute QA boundary and every link before recursion.
      const expected = path.join(run, 'fixture');
      const check = directory => {
        for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
          const item = path.join(directory, entry.name);
          assert(!fs.lstatSync(item).isSymbolicLink(), 'Refuse linked fixture cleanup.');
          assert.equal(fs.realpathSync(item), item, 'Fixture cleanup escaped its owned directory.');
          if (entry.isDirectory()) check(item);
        }
      };
      try {
        assert.equal(fs.realpathSync(appFolder), expected);
        assert.equal(path.dirname(run), fs.realpathSync(output));
        check(appFolder); fs.rmSync(appFolder, { recursive: true, maxRetries: 5, retryDelay: 200 });
        result.fixtureProfileRemoved = !fs.existsSync(appFolder); }
      catch (error) { result.cleanupError = String(error); result.ok = false; }
    }
    fs.writeFileSync(path.join(run, 'electron.stderr.log'), logs.join(''));
    fs.writeFileSync(path.join(run, 'summary.json'), JSON.stringify(result, null, 2) + '\n');
  }
  console.log(JSON.stringify({ ok: result.ok, checks: Object.keys(result.checks).length, output: run, error: result.error }, null, 2));
  if (!result.ok) process.exitCode = 1;
}
main().catch(error => { console.error(error); process.exitCode = 1; });
