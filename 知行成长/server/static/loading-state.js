/* Immediate, accessible feedback while a page waits for saved content. */
(() => {
  function start(parent, title = '正在加载…', detail = '请稍候，可以返回其他页面。') {
    const box = document.createElement('div'); box.className = 'page-loading';
    box.setAttribute('role', 'status'); box.setAttribute('aria-live', 'polite');
    const icon = document.createElement('span'); icon.className = 'page-loading-spinner'; icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('div'), label = document.createElement('strong'), hint = document.createElement('p');
    label.textContent = title; hint.textContent = detail; text.append(label, hint); box.append(icon, text); parent.append(box);
    const timer = setTimeout(() => { if (box.isConnected) hint.textContent = '连接耗时较长，仍在读取，请稍候。'; }, 8000);
    return {finish: () => { clearTimeout(timer); box.remove(); }};
  }
  window.LoadingState = {start};
})();
