// UI defaults only; the sandboxed renderer receives no filesystem or shell API.
if (location.origin === 'http://127.0.0.1:18081') {
  if (!localStorage.getItem('locale')) localStorage.setItem('locale', 'ja-JP');
  if (!localStorage.getItem('i18nextLng')) localStorage.setItem('i18nextLng', 'ja-JP');
  if (!localStorage.getItem('sidebar')) localStorage.setItem('sidebar', 'true');
}
