/* Identity is loaded before business requests; sessions stay in HttpOnly cookies. */
(() => {
  const originalFetch = window.fetch.bind(window);
  const account = window.Account = {user:null};
  const identityBox = document.createElement('div');
  document.querySelector('.topbar').after(identityBox);
  const identityLoading = window.LoadingState?.start(identityBox, '正在验证登录信息…', '验证后会恢复你的学习内容与记录。');
  let switched = false;
  // 账号会话通知：其他标签页登录/退出后，立即暂停旧页面及浏览器模型请求。
  account.isCurrent = id => !switched && account.user?.id === id;
  window.addEventListener('storage', event => {
    if (event.key === 'grow-account-session') accountChanged();
  });
  function loginRedirect(){
    const fragment=/^#(?:plans\/detail\/plan-[a-zA-Z0-9-]{1,70}|mobile\/action\/action-[a-zA-Z0-9-]+|mobile\/practice\/action-[a-zA-Z0-9-]+\/feedback-[a-zA-Z0-9-]+|mobile\/learn\/lesson-[a-z0-9-]{1,70})$/.test(location.hash)?location.hash:'';
    location.replace('/login'+fragment);
  }
  function accountChanged() {
    if (switched) return;
    switched = true;
    window.dispatchEvent(new Event('account-session-changed'));
    document.querySelector('.topbar').inert = true;
    document.querySelector('.wrap').inert = true;
    const notice = document.createElement('div');
    notice.className = 'account-switch-notice';
    notice.innerHTML = '<section role="alert"><h2>当前账号已变更</h2><p>其他标签页切换了账号。此页面已暂停保存，请重新打开后继续使用。</p><a href="/">打开当前账号</a></section>';
    document.body.append(notice);
    notice.querySelector('a').focus();
  }
  account.ready = originalFetch('/api/auth/me', {cache:'no-store'}).then(async response => {
    if (!response.ok) { loginRedirect(); throw new Error('请先登录。'); }
    account.user = (await response.json()).user;
    document.getElementById('accountName').textContent = account.user.username;
    window.dispatchEvent(new Event('ai-config-changed'));
    identityLoading?.finish(); identityBox.remove();
    return account.user;
  }).catch(error => {
    identityLoading?.finish();
    identityBox.setAttribute('role', 'alert'); identityBox.className = 'page-loading';
    identityBox.textContent = '账号连接未完成，请检查网络后重试。';
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn'; retry.textContent = '重新连接'; retry.onclick = () => location.reload(); identityBox.append(retry);
    throw error;
  });
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return originalFetch(input, options);
    await account.ready;
    if (switched) throw new Error('账号已变更，请重新打开页面。');
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : {}));
    headers.set('X-Account-Id', account.user.id);
    const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (!['GET','HEAD','OPTIONS'].includes(method)) headers.set('X-Copilot-Request', '1');
    const response = await originalFetch(input, {...options, headers});
    if (response.status === 401) { accountChanged(); loginRedirect(); throw new Error('登录已过期，请重新登录。'); }
    if (response.headers.get('X-Account-Changed') === '1') { accountChanged(); throw new Error('账号已变更。'); }
    return response;
  };
  account.verify = async (id, signal) => {
    const response = await fetch('/api/auth/me', {cache:'no-store', credentials:'same-origin', signal});
    if (!response.ok) throw new Error('登录信息暂时无法确认，尚未调用模型。');
    const user = (await response.json()).user;
    if (!account.isCurrent(id) || user?.id !== id) {
      accountChanged(); throw new Error('账号已变更，已停止本地执行。');
    }
  };
  account.logout = async () => {
    try {
      if (typeof saveToServer === 'function' && dataLoaded) {
        const generation = editGeneration;
        if (!(await saveToServer()) || editGeneration !== generation) {
          toast('记录尚未保存，请先保存或导出备份。'); return;
        }
      }
      const response = await fetch('/api/auth/logout', {method:'POST'});
      if (!response.ok) throw new Error('退出失败，请重试。');
      try { localStorage.setItem('grow-account-session', Date.now() + ':' + Math.random()); } catch {}
      accountChanged();
      location.replace('/login');
    } catch (error) { toast(error.message); }
  };
  const $ = id => document.getElementById(id);
  let latestInvitation = null;
  const invitationLabels = {active:'待使用', used:'已使用', revoked:'已撤销', expired:'已过期'};
  account.loadInvitations = async () => {
    try {
      const response = await fetch('/api/account/invitations', {cache:'no-store'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || '邀请列表读取失败。');
      const list = $('invitationList');
      list.replaceChildren();
      for (const invitation of result.invitations) {
        const row = document.createElement('div'), text = document.createElement('span');
        row.className = 'invitation-row';
        text.textContent = `${invitationLabels[invitation.status]} · ${new Date(invitation.expires_at * 1000).toLocaleString()} 到期`;
        row.append(text);
        if (invitation.status === 'active') {
          const revoke = document.createElement('button');
          revoke.className = 'btn'; revoke.textContent = '撤销邀请';
          revoke.onclick = async () => {
            revoke.disabled = true;
            try {
              const removed = await fetch('/api/account/invitations/' + invitation.id, {method:'DELETE'});
              const data = await removed.json();
              if (!removed.ok) throw new Error(data.message || '撤销失败，请重试。');
              if (latestInvitation === invitation.id) {
                latestInvitation = null; $('invitationLink').value = ''; $('invitationResult').hidden = true;
              }
              $('invitationStatus').textContent = '邀请已撤销。';
              await account.loadInvitations();
            } catch (error) { $('invitationStatus').textContent = error.message; revoke.disabled = false; }
          };
          row.append(revoke);
        }
        list.append(row);
      }
      if (!result.invitations.length) list.textContent = '还没有创建过邀请。';
    } catch (error) { $('invitationStatus').textContent = error.message; }
  };
  $('invitationCreate').onclick = async () => {
    $('invitationCreate').disabled = true;
    try {
      const response = await fetch('/api/account/invitations', {method:'POST'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || '邀请生成失败，请重试。');
      latestInvitation = result.id;
      $('invitationLink').value = new URL(result.path, location.origin).href;
      $('invitationResult').hidden = false;
      $('invitationStatus').textContent = '邀请已生成，请复制链接发给受邀人。';
      await account.loadInvitations();
      $('invitationLink').focus(); $('invitationLink').select();
    } catch (error) { $('invitationStatus').textContent = error.message; }
    finally { $('invitationCreate').disabled = false; }
  };
  $('invitationCopy').onclick = async () => {
    try {
      await navigator.clipboard.writeText($('invitationLink').value);
      $('invitationStatus').textContent = '邀请链接已复制。';
    } catch (_) {
      $('invitationLink').focus(); $('invitationLink').select();
      $('invitationStatus').textContent = '请手动复制已选中的邀请链接。';
    }
  };
  let saved = null;
  const showMode = () => {
    $('githubCustomFields').hidden = $('githubMode').value !== 'custom';
  };
  $('githubMode').onchange = showMode;
  account.loadStorage = async () => {
    try {
      const response = await fetch('/api/account/github', {cache:'no-store'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.message);
      saved = result;
      $('githubMode').value = result.mode;
      $('githubRepository').value = result.mode === 'custom' ? result.repository : '';
      $('githubBranch').value = result.mode === 'custom' ? result.branch : 'main';
      $('githubToken').value = '';
      $('githubToken').placeholder = result.mode === 'custom' && result.token_configured ? '已保存；留空保留原 Token' : '填写仅授权该仓库的 Token';
      $('githubStatus').textContent = `当前：${result.repository || '未配置 GitHub 仓库'} · ${result.branch}。${result.prefix ? '课程目录：' + result.prefix : '使用原有课程目录。'}${result.token_configured ? '' : '尚未配置凭证。'}`;
      showMode();
    } catch (error) { $('githubStatus').textContent = error.message; }
  };
  async function submitStorage(test) {
    const buttons = [$('githubSave'), $('githubTest')];
    buttons.forEach(button => button.disabled = true);
    $('githubStatus').textContent = test ? '正在检查仓库和分支…' : '正在检查并保存…';
    try {
      const body = {mode:$('githubMode').value, repository:$('githubRepository').value.trim(), branch:$('githubBranch').value.trim(), token:$('githubToken').value};
      if (body.mode === 'custom' && (!body.repository || !body.branch || (!body.token && !(saved?.mode === 'custom' && saved.token_configured)))) throw new Error('请填写仓库、分支和 Token。');
      const response = await fetch('/api/account/github' + (test ? '/test' : ''), {method:test ? 'POST' : 'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || '配置失败，请重试。');
      if (test) $('githubStatus').textContent = result.message;
      else { await account.loadStorage(); toast('GitHub 存储配置已保存'); }
    } catch (error) { $('githubStatus').textContent = error.message; }
    finally { buttons.forEach(button => button.disabled = false); }
  }
  $('githubSave').onclick = () => submitStorage(false);
  $('githubTest').onclick = () => submitStorage(true);
})();
