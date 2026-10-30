(() => {
  let mode = 'login';
  let invitation = '';
  let submitting = false;
  const $ = id => document.getElementById(id);
  function choose(next) {
    if (next === 'register' && !invitation) return;
    mode = next;
    const registering = mode === 'register';
    const unified = mode === 'zook';
    $('loginTab').setAttribute('aria-pressed', String(!registering));
    $('registerTab').setAttribute('aria-pressed', String(registering));
    $('zookLoginTab')?.setAttribute('aria-pressed', String(unified));
    $('username').maxLength = unified ? 254 : 32;
    if ($('accountLabel')) $('accountLabel').textContent = unified ? 'LightTick账号（邮箱或手机号）' : '用户名';
    $('loginTitle').textContent = registering ? '开始积累你的成长' : '继续你的学习';
    $('loginDescription').textContent = registering ? '用户名使用 3–32 位字母、数字、下划线或短横线，密码至少 10 位。' : '登录后，接着记录每一天的思考与成长。';
    if (unified) $('loginDescription').textContent = '使用已明确关联的LightTick账号继续。首次关联请先用原Grow账号登录，在设置中完成。';
    $('authSubmit').textContent = registering ? '注册并开始学习' : '登录';
    $('password').autocomplete = registering ? 'new-password' : 'current-password';
    $('password').minLength = registering ? 10 : 1;
    $('confirmField').hidden = !registering;
    $('confirmPassword').required = registering;
    $('authMessage').textContent = '';
  }
  $('loginTab').onclick = () => choose('login');
  $('registerTab').onclick = () => choose('register');
  window.GrowLogin = {choose};
  function readInvitation() {
    invitation = new URLSearchParams(location.hash.slice(1)).get('invite') || '';
    $('registerTab').hidden = !invitation;
    $('invitationNotice').textContent = invitation
      ? '你正在通过邀请注册。每个邀请仅可使用一次，有效期为 7 天。'
      : '暂不开放直接注册，请向已有账号的用户获取邀请链接。每个账号独立保存学习内容和记录。';
    choose(invitation ? 'register' : 'login');
  }
  window.addEventListener('hashchange', readInvitation);
  readInvitation();
  $('authForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting) return;
    if (mode === 'register' && $('password').value !== $('confirmPassword').value) {
      $('authMessage').textContent = '两次密码不一致，请重新填写。';
      $('confirmPassword').focus(); return;
    }
    submitting = true;
    const controls = [$('authSubmit'), $('loginTab'), $('registerTab'), $('zookLoginTab')].filter(Boolean);
    controls.forEach(control => control.disabled = true);
    $('authForm').setAttribute('aria-busy', 'true');
    $('authMessage').replaceChildren();
    $('authSubmit').textContent = mode === 'register' ? '正在创建…' : '正在登录…';
    const loading = window.LoadingState?.start($('authMessage'), mode === 'register' ? '正在创建账号…' : '正在登录…', '正在确认账号信息，请勿重复提交。');
    if (!loading) $('authMessage').textContent = mode === 'register' ? '正在创建账号…' : '正在登录…';
    try {
      const response = await fetch('/api/auth/' + (mode === 'zook' ? 'zook/login' : mode), {
        method:'POST', headers:{'Content-Type':'application/json', 'X-Copilot-Request':'1'},
        body:JSON.stringify({[mode === 'zook' ? 'account' : 'username']:$('username').value.trim(), password:$('password').value,
          ...(mode === 'register' ? {invitation} : {})})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || '暂时无法登录，请稍后再试。');
      try { localStorage.setItem('grow-account-session', Date.now() + ':' + Math.random()); } catch {}
      $('authMessage').textContent = mode === 'register' ? '账号已创建，正在打开学习首页…' : '登录成功，正在打开学习首页…';
      const continuation=/^#(?:plans\/detail\/plan-[a-zA-Z0-9-]{1,70}|mobile\/action\/action-[a-zA-Z0-9-]+|mobile\/practice\/action-[a-zA-Z0-9-]+\/feedback-[a-zA-Z0-9-]+|mobile\/learn\/lesson-[a-z0-9-]{1,70})$/.test(location.hash)?location.hash:'';
      location.replace('/'+continuation);
    } catch (error) {
      $('authMessage').textContent = error.message === 'Failed to fetch' ? '连接中断，请检查网络后重试。' : error.message;
      submitting = false; controls.forEach(control => control.disabled = false);
      $('authSubmit').textContent = mode === 'register' ? '注册并开始学习' : '登录';
    } finally {
      loading?.finish(); $('authForm').removeAttribute('aria-busy');
    }
  });
})();
