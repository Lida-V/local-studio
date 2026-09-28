// Trusted project controls in an isolated preload; no raw IPC or path setter is exposed.
const { ipcRenderer } = require('electron');
if (location.origin === 'http://127.0.0.1:18081' && process.isMainFrame) {
  if (!localStorage.getItem('locale')) localStorage.setItem('locale', 'ja-JP');
  if (!localStorage.getItem('i18nextLng')) localStorage.setItem('i18nextLng', 'ja-JP');
  if (!localStorage.getItem('sidebar')) localStorage.setItem('sidebar', 'true');
  window.addEventListener('DOMContentLoaded', () => {
    const host = document.createElement('aside');
    host.id = 'local-studio-project-bar';
    host.style.cssText = 'position:fixed;inset:0 0 auto 0;height:44px;z-index:2147483647';
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
    const pageStyle = document.createElement('style');
    pageStyle.textContent = 'html,body{height:100%!important;overflow:hidden!important}body>div[style*="display: contents"]{display:block!important;position:absolute!important;inset:44px 0 0!important;transform:translateZ(0);height:calc(100dvh - 44px)!important}body .h-screen,body .h-dvh,body [class~="h-[100dvh]"]{height:calc(100dvh - 44px)!important}body .min-h-screen,body .min-h-dvh,body [class~="min-h-[100dvh]"]{min-height:calc(100dvh - 44px)!important}';
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
