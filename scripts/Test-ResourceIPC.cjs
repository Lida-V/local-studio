// Exercise the real main-process handler with a synthetic Electron app.
// No windows, commands, files, models or conversations are touched.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/main.cjs'), 'utf8');
const handlers = new Map();
let ready, mainWindow, pendingCommand, calls = 0, now = 10000;
const noop = () => {};
class Window {
  constructor() {
    this.webContents = { mainFrame: { url: 'http://127.0.0.1:18081/' }, on: noop,
      setWindowOpenHandler: noop, send: noop };
    mainWindow = this;
  }
  on() {} once() {} async loadURL() {} isDestroyed() { return false; }
}
const electron = {
  app: { setName: noop, setAppUserModelId: noop, setPath: noop, commandLine: { appendSwitch: noop },
    requestSingleInstanceLock: () => true, on: noop,
    whenReady: () => ({ then(fn) { ready = fn; return { catch: noop }; } }) },
  BrowserWindow: Window, Menu: { setApplicationMenu: noop, buildFromTemplate: x => x },
  session: { fromPartition: () => ({ setPermissionRequestHandler: noop, setPermissionCheckHandler: noop,
    setSpellCheckerEnabled: noop, webRequest: { onBeforeRequest: noop }, isPersistent: () => false }) },
  dialog: {}, shell: {}, ipcMain: { handle: (name, fn) => handlers.set(name, fn) }
};
const fakeFs = { mkdirSync: noop, watchFile: noop, writeFileSync: noop };
const fakeRequire = name => name === 'electron' ? electron : name === 'node:fs' ? fakeFs :
  name === 'node:child_process' ? { execFile(exe, args, options, callback) {
    calls++;
    assert.ok(exe.endsWith('python.exe'));
    assert.equal(options.windowsHide, true);
    assert.deepEqual(Array.from(args).slice(-1), ['resource-status']);
    pendingCommand = callback;
  } } : require(name);
class Clock extends Date { static now() { return now; } }
async function test() {
  vm.runInNewContext(source, { require: fakeRequire, __dirname: path.join(__dirname, '../desktop'),
    process: { env: { LOCAL_STUDIO_SOURCE: 'fixture-source' }, versions: { electron: 'fixture' } },
    URL, Promise, Date: Clock });
  await ready();
  const handler = handlers.get('resources:status');
  const valid = { sender: mainWindow.webContents, senderFrame: mainWindow.webContents.mainFrame };
  for (const event of [{ ...valid, sender: {} }, { ...valid, senderFrame: { url: valid.senderFrame.url } }]) {
    assert.throws(() => handler(event));
  }
  valid.senderFrame.url = 'https://example.invalid/';
  assert.throws(() => handler(valid));
  assert.equal(calls, 0, 'invalid senders must never spawn a sampler');
  valid.senderFrame.url = 'http://127.0.0.1:18081/';
  const first = handler(valid, 'ignored-renderer-command');
  const second = handler(valid);
  assert.equal(calls, 1, 'overlapping polls share the same sampler');
  pendingCommand(null, '{"schemaVersion":1,"cpu":{"percent":12}}');
  assert.equal((await first).cpu.percent, 12);
  assert.equal((await second).cpu.percent, 12);
  await handler(valid);
  assert.equal(calls, 1, 'recent samples are cached');
  now += 2100;
  const failed = handler(valid);
  pendingCommand(new Error('fixture failure'));
  await assert.rejects(failed, /PCリソース/);
  const retry = handler(valid);
  assert.equal(calls, 3, 'failed samplers must allow a subsequent retry');
  pendingCommand(null, '{"schemaVersion":1,"cpu":{"percent":18}}');
  assert.equal((await retry).cpu.percent, 18);
  console.log('Resource IPC: sender/frame/origin guards, fixed command, deduplication, cache, retry PASS');
}
test().catch(error => { console.error(error); process.exitCode = 1; });
