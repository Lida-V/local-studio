const { app, BrowserWindow, Menu, session, dialog } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const root = 'C:/AI/LocalLLM';
const ephemeral = path.join(root, 'cache/desktop-session');
const origin = 'http://127.0.0.1:18081';
fs.mkdirSync(ephemeral, { recursive: true });
app.setName('Local Studio');
app.setAppUserModelId('LocalStudio.Desktop');
app.setPath('userData', ephemeral);
app.setPath('sessionData', ephemeral);
app.setPath('crashDumps', path.join(ephemeral, 'crashes'));
app.commandLine.appendSwitch('disable-http-cache');
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
app.commandLine.appendSwitch('lang', 'ja');
let window;
let webSession;
let cleaned = false;
const local = url => { try { return new URL(url).origin === origin; } catch { return false; } };
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (window) { window.restore(); window.focus(); } });
  app.whenReady().then(async () => {
    webSession = session.fromPartition('local-studio-memory', { cache: false });
    webSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    webSession.setPermissionCheckHandler(() => false);
    webSession.setSpellCheckerEnabled(false);
    webSession.webRequest.onBeforeRequest((details, callback) => {
      const u = new URL(details.url);
      callback({ cancel: !(['data:', 'blob:'].includes(u.protocol) || local(details.url) || (u.protocol === 'ws:' && u.host === '127.0.0.1:18081')) });
    });
    window = new BrowserWindow({
      width: 1280, height: 880, minWidth: 760, minHeight: 560,
      title: 'Local Studio', backgroundColor: '#171717', show: false,
      webPreferences: { session: webSession, preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false }
    });
    window.on('page-title-updated', event => { event.preventDefault(); window.setTitle('Local Studio'); });
    window.webContents.on('will-navigate', (event, url) => { if (!local(url)) event.preventDefault(); });
    window.webContents.on('will-redirect', (event, url) => { if (!local(url)) event.preventDefault(); });
    window.webContents.setWindowOpenHandler(({ url }) => {
      if (local(url)) window.loadURL(url);
      return { action: 'deny' };
    });
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: 'チャット', submenu: [
        { label: '新しいセッション', accelerator: 'CmdOrCtrl+N', click: () => window.loadURL(origin) },
        { type: 'separator' }, { label: '終了', role: 'quit' }
      ] },
      { label: '編集', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
      { label: '表示', submenu: [{ label: '再読み込み', role: 'reload' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] }
    ]));
    window.once('ready-to-show', () => window.show());
    await window.loadURL(origin);
    fs.writeFileSync(path.join(root, 'runtime/desktop.json'), JSON.stringify({ pid: process.pid, version: process.versions.electron, cache: ephemeral, persistentSession: webSession.isPersistent(), started: new Date().toISOString() }));
  }).catch(error => { dialog.showErrorBox('Local Studio', error.message); app.exit(1); });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', event => {
    if (cleaned || !webSession) return;
    event.preventDefault();
    Promise.all([webSession.clearCache(), webSession.clearStorageData(), webSession.clearCodeCaches({})]).finally(() => { cleaned = true; app.quit(); });
  });
}
