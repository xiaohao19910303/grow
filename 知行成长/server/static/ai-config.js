/* AI credentials belong to this browser origin, never the application database. */
(() => {
  const legacyKey = 'zhixing-ai-config-v1';
  function storageKey() {
    const user = window.Account?.user;
    if (!user) return null;
    const key = legacyKey + ':' + user.id;
    if (user.is_owner && !localStorage.getItem(key) && localStorage.getItem(legacyKey)) {
      localStorage.setItem(key, localStorage.getItem(legacyKey));
      localStorage.removeItem(legacyKey);
    }
    return key;
  }
  const missing = '请先在「设置与数据」中保存自己的 Base URL、API Key 和模型名称。';
  function read() {
    try {
      const value = JSON.parse((storageKey() && localStorage.getItem(storageKey())) || '{}');
      return Object.fromEntries(['api_base_url', 'api_key', 'model_name'].map(k => [k, typeof value?.[k] === 'string' ? value[k] : '']));
    } catch (_) { return {api_base_url: '', api_key: '', model_name: ''}; }
  }
  function field(value, name, limit) {
    if(typeof value !== 'string' || !value.trim())throw new Error(missing);
    if(value.length>limit || /[\x00-\x1f]/.test(value))throw new Error(name+'超长或含有换行等控制字符，请检查后重新填写。');
    return value.trim();
  }
  function address(value) {
    value=field(value,'Base URL',2048);
    let url;
    try { url = new URL(value); } catch (_) { throw new Error('请填写有效的 HTTPS Base URL。'); }
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.search || url.hash) throw new Error('请填写无账号、查询参数和片段的 HTTPS Base URL。');
    return value;
  }
  function validate(value) {
    return {api_base_url:address(value?.api_base_url),api_key:field(value?.api_key,'API Key',4096),model_name:field(value?.model_name,'模型名称',100)};
  }
  window.AIConfig = {
    read,
    address,
    validate,
    require: () => validate(read()),
    status: () => { try { validate(read()); return ''; } catch (e) { return e.message; } },
    save: value => {
      const clean = validate(value);
      try { const key = storageKey();
        if (!key) throw new Error('请先登录。');
        localStorage.setItem(key, JSON.stringify(clean)); }
      catch (_) { throw new Error('浏览器不允许保存配置，请检查站点存储权限。'); }
      window.dispatchEvent(new Event('ai-config-changed'));
    },
    clear: () => {
      if (storageKey()) localStorage.removeItem(storageKey());
      window.dispatchEvent(new Event('ai-config-changed'));
    },
  };
})();
