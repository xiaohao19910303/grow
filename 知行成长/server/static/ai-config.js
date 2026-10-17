/* AI credentials belong to this browser origin, never the application database. */
(() => {
  const storageKey = 'zhixing-ai-config-v1';
  const missing = '请先在「设置与数据」中保存自己的 Base URL、API Key 和模型名称。';
  function read() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || '{}');
      return Object.fromEntries(['api_base_url', 'api_key', 'model_name'].map(k => [k, typeof value?.[k] === 'string' ? value[k] : '']));
    } catch (_) { return {api_base_url: '', api_key: '', model_name: ''}; }
  }
  function validate(value) {
    if (!value.api_base_url || !value.api_key || !value.model_name) throw new Error(missing);
    let url;
    try { url = new URL(value.api_base_url); } catch (_) { throw new Error('请填写有效的 HTTPS Base URL。'); }
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new Error('请填写无账号、查询参数和片段的 HTTPS Base URL。');
    return value;
  }
  window.AIConfig = {
    read,
    require: () => validate(read()),
    status: () => { try { validate(read()); return ''; } catch (e) { return e.message; } },
    save: value => {
      const clean = Object.fromEntries(['api_base_url', 'api_key', 'model_name'].map(k => [k, String(value[k] || '').trim()]));
      validate(clean);
      try { localStorage.setItem(storageKey, JSON.stringify(clean)); }
      catch (_) { throw new Error('浏览器不允许保存配置，请检查站点存储权限。'); }
      window.dispatchEvent(new Event('ai-config-changed'));
    },
    clear: () => {
      localStorage.removeItem(storageKey);
      window.dispatchEvent(new Event('ai-config-changed'));
    },
  };
})();
