'use strict';
const el = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
let profiles = [];
function select(profile) {
  const guide = document.querySelector('#guide'); guide.replaceChildren();
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.id === profile.id));
  guide.append(el('div', profile.status, 'badge'), el('h2', profile.label), el('small', profile.engine + ' · ' + (profile.environmentPresent ? '既存環境あり / 学習未検証' : '接続先は未設定')));
  guide.append(el('p', profile.dataset));
  const list = el('ol'); profile.steps.forEach(s => list.append(el('li', s))); guide.append(list, el('p', profile.note, 'note'), el('p', profile.url, 'url'));
  const row = el('div', '', 'row'); const input = el('input'); input.placeholder = '例: my-character-v1'; input.setAttribute('aria-label', '準備プロジェクト名'); input.maxLength = 64;
  const create = el('button', '準備フォルダを作成', 'primary');
  create.onclick = async () => { create.disabled = true; try { const result = await window.training.prepare(profile.id, input.value.trim()); document.querySelector('#result').textContent = '作成しました。学習は開始していません。\n' + result.prepared; } catch (error) { document.querySelector('#result').textContent = error.message; } finally { create.disabled = false; } };
  const open = el('button', '準備フォルダを開く'); open.onclick = async () => { try { await window.training.openFolder(); } catch(error) { document.querySelector('#result').textContent = error.message; } };
  row.append(input, create, open); guide.append(row);
}
window.training.profiles().then(items => { profiles = items; const nav = document.querySelector('#models'); items.forEach(p => { const b = el('button', p.label); b.dataset.id = p.id; b.append(el('small', p.type)); b.onclick = () => select(p); nav.append(b); }); select(items[0]); }).catch(e => document.querySelector('#result').textContent = e.message);
