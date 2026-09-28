// Trusted project controls in an isolated preload; no raw IPC or path setter is exposed.
const { ipcRenderer } = require('electron');
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
