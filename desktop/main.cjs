const { app, BrowserWindow, Menu, session, dialog, ipcMain, shell } = require('electron');
const { pathToFileURL } = require('node:url');
const { execFile } = require('node:child_process');
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
let trainingWindow;
const trainingUrl = pathToFileURL(path.join(__dirname, 'training.html')).href;
const trainingAssets = new Set(['training.html','training-ui.js'].map(name => pathToFileURL(path.join(__dirname, name)).href));
function studioCommand(args) {
  const source = process.env.LOCAL_STUDIO_SOURCE;
  if (!source) return Promise.reject(new Error('専用ランチャーからLocal Studioを起動してください。'));
  const python = path.join(root, 'apps/open-webui/.venv/Scripts/python.exe');
  return new Promise((resolve, reject) => execFile(python, ['-X','utf8',path.join(source,'scripts/Local-Studio.py'),...args], { windowsHide: true, timeout: 15000, maxBuffer: 1024 * 1024 }, (error, stdout) => {
    if (error) return reject(new Error('操作できませんでした。フォルダの存在・アクセス権、準備フォルダ名の重複を確認してください。'));
    try { resolve(JSON.parse(stdout)); } catch (e) { reject(e); }
  }));
}
const trainingCommand = studioCommand;
let choosingProject = false;
function checkProjectSender(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || !local(event.senderFrame.url)) throw new Error('Invalid project page');
}
async function refreshProject() {
  try {
    const value = await studioCommand(['project']);
    if (window && !window.isDestroyed()) window.webContents.send('project:changed', value);
    return value;
  } catch (error) {
    if (window && !window.isDestroyed()) window.webContents.send('project:changed', { error: error.message });
    throw error;
  }
}
async function chooseProject() {
  if (choosingProject) return;
  choosingProject = true;
  try {
    const current = await studioCommand(['project']).catch(() => ({}));
    const result = await dialog.showOpenDialog(window, { title: '作業するプロジェクトフォルダを選択', buttonLabel: 'このフォルダで作業', defaultPath: current.path || path.join(root,'workspace'), properties: ['openDirectory','dontAddToRecent'] });
    if (!result.canceled && result.filePaths.length === 1) {
      await studioCommand(['project-select', result.filePaths[0]]);
      if (trainingWindow) trainingWindow.reload();
    }
    return await refreshProject();
  } finally { choosingProject = false; }
}
async function resetProject() {
  await studioCommand(['project-reset']);
  if (trainingWindow) trainingWindow.reload();
  return refreshProject();
}
async function openProject() {
  const current = await studioCommand(['project']);
  const error = await shell.openPath(current.path);
  if (error) throw new Error(error);
}
const menuAction = action => () => action().catch(error => dialog.showErrorBox('Local Studio', error.message));
ipcMain.handle('project:info', event => { checkProjectSender(event); return studioCommand(['project']); });
ipcMain.handle('project:choose', event => { checkProjectSender(event); return chooseProject(); });
ipcMain.handle('project:reset', event => { checkProjectSender(event); return resetProject(); });
ipcMain.handle('project:open', event => { checkProjectSender(event); return openProject(); });
function checkTrainingSender(event) {
  if (!trainingWindow || event.sender !== trainingWindow.webContents || event.senderFrame.url !== trainingUrl) throw new Error('Invalid training page');
}
ipcMain.handle('training:profiles', event => { checkTrainingSender(event); return trainingCommand(['training-guide']); });
ipcMain.handle('training:prepare', (event, model, name) => {
  checkTrainingSender(event);
  if (!['anima','qwen-image-2.1','minimax-h3','qwen3.8'].includes(model) || typeof name !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name)) throw new Error('モデルと英数字のプロジェクト名を指定してください。');
  return trainingCommand(['prepare-training',model,name]);
});
ipcMain.handle('training:open-folder', async event => {
  checkTrainingSender(event);
  const current = await studioCommand(['project']);
  const folder = path.join(current.path,'training'); fs.mkdirSync(folder,{recursive:true});
  const error = await shell.openPath(folder); if (error) throw new Error(error);
});
function showTraining() {
  if (trainingWindow) { trainingWindow.show(); trainingWindow.focus(); return; }
  trainingWindow = new BrowserWindow({ width: 1080, height: 840, minWidth: 700, minHeight: 600, title: 'LoRA学習の準備 · Local Studio', backgroundColor: '#14161b', webPreferences: { session: webSession, preload: path.join(__dirname,'training-preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  trainingWindow.webContents.on('will-navigate', event => event.preventDefault());
  trainingWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  trainingWindow.on('closed', () => { trainingWindow = null; });
  trainingWindow.loadURL(trainingUrl);
}
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
      callback({ cancel: !(trainingAssets.has(details.url) || ['data:', 'blob:'].includes(u.protocol) || local(details.url) || (u.protocol === 'ws:' && u.host === '127.0.0.1:18081')) });
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
      { label: 'プロジェクト', submenu: [
        { label: 'フォルダを選択…', accelerator: 'CmdOrCtrl+Alt+O', click: menuAction(chooseProject) },
        { label: '作業フォルダを開く', click: menuAction(openProject) },
        { type: 'separator' }, { label: '標準workspaceへ戻す', click: menuAction(resetProject) }
      ] },
      { label: 'チャット', submenu: [
        { label: '新しいセッション', accelerator: 'CmdOrCtrl+N', click: () => window.loadURL(origin) },
        { type: 'separator' }, { label: '終了', role: 'quit' }
      ] },
      { label: '制作', submenu: [{ label: 'LoRA学習の準備', accelerator: 'CmdOrCtrl+Shift+L', click: showTraining }] },
      { label: '編集', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
      { label: '表示', submenu: [{ label: '再読み込み', role: 'reload' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] }
    ]));
    window.once('ready-to-show', () => window.show());
    await window.loadURL(origin);
    window.on('focus', () => refreshProject().catch(() => {}));
    fs.watchFile(path.join(root,'data/project-workspace.json'), { interval: 2000, persistent: false }, () => refreshProject().catch(() => {}));
    fs.writeFileSync(path.join(root, 'runtime/desktop.json'), JSON.stringify({ pid: process.pid, version: process.versions.electron, cache: ephemeral, persistentSession: webSession.isPersistent(), started: new Date().toISOString() }));
  }).catch(error => { dialog.showErrorBox('Local Studio', error.message); app.exit(1); });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', event => {
    if (cleaned || !webSession) return;
    event.preventDefault();
    Promise.all([webSession.clearCache(), webSession.clearStorageData(), webSession.clearCodeCaches({})]).finally(() => { cleaned = true; app.quit(); });
  });
}
